from types import SimpleNamespace

import httpx
import pytest
from qdrant_client.http import models

from app.services.vector_store import QdrantVectorStore


class FakeEmbeddingClient:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dimension for _ in texts]


class EmptyProbeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


class UnreachableEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        req = httpx.Request("POST", "http://unresolvable.invalid/v1/embeddings")
        raise httpx.ConnectError("[Errno -5] No address associated with hostname", request=req)


class FakeQdrantClient:
    def __init__(self, existing_size: int | None = None) -> None:
        self.existing_size = existing_size
        self.deleted_collections: list[str] = []
        self.created_collections: list[tuple[str, int]] = []

    def get_collections(self):
        collections = []
        if self.existing_size is not None:
            collections.append(SimpleNamespace(name="story_chunks"))
        return SimpleNamespace(collections=collections)

    def get_collection(self, collection_name: str):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=models.VectorParams(size=self.existing_size, distance=models.Distance.COSINE)
                )
            )
        )

    def create_collection(self, collection_name: str, vectors_config):
        self.created_collections.append((collection_name, int(vectors_config.size)))

    def delete_collection(self, collection_name: str):
        self.deleted_collections.append(collection_name)
        self.existing_size = None


def test_qdrant_store_raises_when_embedding_dimension_mismatches_config(monkeypatch) -> None:
    fake_client = FakeQdrantClient()
    monkeypatch.setattr("app.services.vector_store.QdrantClient", lambda url: fake_client)

    with pytest.raises(RuntimeError) as exc_info:
        QdrantVectorStore(
            url="http://qdrant:6333",
            collection_name="story_chunks",
            vector_size=64,
            embedding_client=FakeEmbeddingClient(1024),
        )

    assert "NOVEL_BUILDER_QDRANT_VECTOR_SIZE=64" in str(exc_info.value)
    assert "embedding_dimension=1024" in str(exc_info.value)


def test_qdrant_store_raises_clear_error_when_existing_collection_dimension_mismatches(monkeypatch) -> None:
    fake_client = FakeQdrantClient(existing_size=64)
    monkeypatch.setattr("app.services.vector_store.QdrantClient", lambda url: fake_client)

    with pytest.raises(RuntimeError) as exc_info:
        QdrantVectorStore(
            url="http://qdrant:6333",
            collection_name="story_chunks",
            vector_size=1024,
            embedding_client=FakeEmbeddingClient(1024),
        )

    assert "currently uses dim=64" in str(exc_info.value)
    assert "expects dim=1024" in str(exc_info.value)
    assert "NOVEL_BUILDER_QDRANT_RECREATE_ON_DIMENSION_MISMATCH=true" in str(exc_info.value)


def test_qdrant_store_recreates_collection_when_enabled(monkeypatch) -> None:
    fake_client = FakeQdrantClient(existing_size=64)
    monkeypatch.setattr("app.services.vector_store.QdrantClient", lambda url: fake_client)

    store = QdrantVectorStore(
        url="http://qdrant:6333",
        collection_name="story_chunks",
        vector_size=1024,
        embedding_client=FakeEmbeddingClient(1024),
        recreate_on_dimension_mismatch=True,
    )

    assert store.vector_size == 1024
    assert fake_client.deleted_collections == ["story_chunks"]
    assert fake_client.created_collections == [("story_chunks", 1024)]


def test_qdrant_store_uses_config_vector_size_when_embedding_probe_unreachable(monkeypatch) -> None:
    fake_client = FakeQdrantClient()
    monkeypatch.setattr("app.services.vector_store.QdrantClient", lambda url: fake_client)

    store = QdrantVectorStore(
        url="http://qdrant:6333",
        collection_name="story_chunks",
        vector_size=3072,
        embedding_client=UnreachableEmbeddingClient(),
    )

    assert store.embedding_dimension == 3072


def test_qdrant_store_init_fails_on_empty_embedding_probe(monkeypatch) -> None:
    fake_client = FakeQdrantClient()
    monkeypatch.setattr("app.services.vector_store.QdrantClient", lambda url: fake_client)

    with pytest.raises(RuntimeError) as exc_info:
        QdrantVectorStore(
            url="http://qdrant:6333",
            collection_name="story_chunks",
            vector_size=64,
            embedding_client=EmptyProbeEmbeddingClient(),
        )

    assert "empty vector during startup validation" in str(exc_info.value).lower()
