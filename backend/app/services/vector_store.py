from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from time import sleep
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.logging import get_logger
from app.domain.schema import VectorDocument
from app.services.llm import EmbeddingClient

logger = get_logger(__name__)


class VectorStore(Protocol):
    def add_documents(self, story_id: str, documents: list[VectorDocument]) -> None:
        ...

    def remove_story(self, story_id: str) -> None:
        """Remove all vector chunks indexed for this story."""
        ...

    def search(self, story_id: str, query: str, limit: int = 5) -> list[VectorDocument]:
        ...


def deterministic_embedding(text: str, size: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for index in range(size):
        byte = digest[index % len(digest)]
        values.append((byte / 255.0) * 2.0 - 1.0)
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


@dataclass
class DeterministicEmbeddingClient:
    vector_size: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [deterministic_embedding(text, self.vector_size) for text in texts]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return sum(l * r for l, r in zip(left, right, strict=False)) / (left_norm * right_norm)


@dataclass
class InMemoryVectorStore:
    embedding_client: EmbeddingClient = field(default_factory=lambda: DeterministicEmbeddingClient(64))
    story_documents: dict[str, list[VectorDocument]] = field(default_factory=lambda: defaultdict(list))
    story_vectors: dict[str, list[list[float]]] = field(default_factory=lambda: defaultdict(list))

    def add_documents(self, story_id: str, documents: list[VectorDocument]) -> None:
        if not documents:
            return
        vectors = self.embedding_client.embed_texts([document.text_chunk for document in documents])
        self.story_documents[story_id].extend(documents)
        self.story_vectors[story_id].extend(vectors)

    def remove_story(self, story_id: str) -> None:
        self.story_documents.pop(story_id, None)
        self.story_vectors.pop(story_id, None)

    def search(self, story_id: str, query: str, limit: int = 5) -> list[VectorDocument]:
        documents = self.story_documents.get(story_id, [])
        vectors = self.story_vectors.get(story_id, [])
        if not documents or not vectors:
            return []
        query_vector = self.embedding_client.embed_texts([query])[0]
        scored = sorted(
            zip(documents, vectors, strict=False),
            key=lambda row: cosine_similarity(query_vector, row[1]),
            reverse=True,
        )
        return [document for document, _vector in scored[:limit]]


class QdrantVectorStore:
    def __init__(
        self,
        url: str,
        collection_name: str,
        vector_size: int,
        embedding_client: EmbeddingClient,
        recreate_on_dimension_mismatch: bool = False,
    ) -> None:
        self.client = QdrantClient(url=url)
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.embedding_client = embedding_client
        self.recreate_on_dimension_mismatch = recreate_on_dimension_mismatch
        self.max_retries = 10
        self.retry_delay_seconds = 1.0
        self.embedding_dimension = self._detect_embedding_dimension()
        self._validate_embedding_dimension()
        self._ensure_collection()

    def _with_retry(self, operation) -> None:
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                return operation()
            except (UnexpectedResponse, RuntimeError) as exc:
                last_error = exc
                sleep(self.retry_delay_seconds)
        if last_error is not None:
            raise last_error

    def _ensure_collection(self) -> None:
        def operation() -> None:
            collections = self.client.get_collections().collections
            if any(collection.name == self.collection_name for collection in collections):
                current_size = self._get_collection_vector_size()
                if current_size != self.vector_size:
                    if self.recreate_on_dimension_mismatch:
                        self.client.delete_collection(collection_name=self.collection_name)
                    else:
                        raise RuntimeError(self._build_dimension_mismatch_message(current_size))
                else:
                    return
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
            )
        self._with_retry(operation)

    def _detect_embedding_dimension(self) -> int:
        try:
            vectors = self.embedding_client.embed_texts(["vector-dimension-probe"])
        except httpx.RequestError as exc:
            # DNS/connect/timeouts during startup should not take down unrelated API routes
            # (e.g. macro-snapshot) that only need WorkflowService construction.
            logger.warning(
                "embedding_dimension_probe_unreachable",
                extra={
                    "extra_payload": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "fallback_vector_size": self.vector_size,
                    }
                },
            )
            return int(self.vector_size)
        except OSError as exc:
            logger.warning(
                "embedding_dimension_probe_os_error",
                extra={
                    "extra_payload": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "fallback_vector_size": self.vector_size,
                    }
                },
            )
            return int(self.vector_size)
        if not vectors or not vectors[0]:
            raise RuntimeError(
                "Embedding client returned an empty vector during startup validation."
            )
        return len(vectors[0])

    def _validate_embedding_dimension(self) -> None:
        if self.embedding_dimension != self.vector_size:
            raise RuntimeError(
                "Configured Qdrant vector size does not match embedding output dimension. "
                f"NOVEL_BUILDER_QDRANT_VECTOR_SIZE={self.vector_size}, "
                f"embedding_dimension={self.embedding_dimension}. "
                "Update NOVEL_BUILDER_QDRANT_VECTOR_SIZE to the embedding model dimension "
                "or switch to a matching embedding model."
            )

    def _get_collection_vector_size(self) -> int:
        info = self.client.get_collection(self.collection_name)
        vectors_config = getattr(getattr(info, "config", None), "params", None)
        raw_vectors = getattr(vectors_config, "vectors", None)
        if hasattr(raw_vectors, "size"):
            return int(raw_vectors.size)
        if isinstance(raw_vectors, dict):
            first_vector = next(iter(raw_vectors.values()))
            if hasattr(first_vector, "size"):
                return int(first_vector.size)
        raise RuntimeError(
            f"Unable to determine vector size for Qdrant collection '{self.collection_name}'."
        )

    def _build_dimension_mismatch_message(self, current_size: int) -> str:
        return (
            "Qdrant collection dimension mismatch detected during backend startup. "
            f"Collection '{self.collection_name}' currently uses dim={current_size}, "
            f"but backend expects dim={self.vector_size} and embedding model returns "
            f"dim={self.embedding_dimension}. "
            "Set NOVEL_BUILDER_QDRANT_VECTOR_SIZE to the embedding dimension and recreate the "
            "collection, or enable NOVEL_BUILDER_QDRANT_RECREATE_ON_DIMENSION_MISMATCH=true "
            "to let the backend rebuild this collection automatically."
        )

    def add_documents(self, story_id: str, documents: list[VectorDocument]) -> None:
        if not documents:
            return
        vectors = self.embedding_client.embed_texts([document.text_chunk for document in documents])
        points = []
        for index, (document, vector) in enumerate(zip(documents, vectors, strict=False)):
            payload = {"story_id": story_id, "text_chunk": document.text_chunk, **document.metadata}
            # Prefer stable chunk_id-based IDs when provided so overwrites are deterministic.
            chunk_id = str(payload.get("chunk_id") or "").strip()
            if chunk_id:
                point_key = f"{story_id}:{payload.get('chapter_id', '')}:{chunk_id}"
            else:
                point_key = f"{story_id}:{payload.get('chapter_id', '')}:{index}:{document.text_chunk}"
            point_id = str(uuid5(NAMESPACE_URL, point_key))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(self, story_id: str, query: str, limit: int = 5) -> list[VectorDocument]:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="story_id", match=models.MatchValue(value=story_id))]
        )
        query_vector = self.embedding_client.embed_texts([query])[0]
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
            )
            results = response.points
        else:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
            )
        documents: list[VectorDocument] = []
        for result in results:
            payload = dict(result.payload or {})
            text_chunk = payload.pop("text_chunk", "")
            payload.pop("story_id", None)
            documents.append(VectorDocument(text_chunk=text_chunk, metadata=payload))
        return documents

    def remove_story(self, story_id: str) -> None:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="story_id", match=models.MatchValue(value=story_id))]
        )
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(filter=query_filter),
            )
        except (UnexpectedResponse, ValueError, TypeError):
            # Best-effort: schema/version differences; ignore if delete-by-filter unsupported
            pass
