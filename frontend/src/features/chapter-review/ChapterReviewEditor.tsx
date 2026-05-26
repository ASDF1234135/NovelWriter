import { useEffect, useMemo } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import Document from "@tiptap/extension-document";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import HardBreak from "@tiptap/extension-hard-break";

export type ChapterReviewEditorProps = {
  initialDoc: string;
  busy?: boolean;
  /**
   * When true, editor chrome uses warm ink-on-cream tones for the atelier
   * manuscript surface (review shell). Default matches the dark app shell.
   */
  manuscriptSurface?: boolean;
  /** Emits the plain-text manuscript (paragraphs separated by blank lines). */
  onChange: (plainText: string) => void;
};

/**
 * Lazy-loaded by ChapterReviewGate via React.lazy(); keeps TipTap and
 * ProseMirror out of the main bundle. The exported value MUST be `default`.
 */
function toProseMirrorDoc(plain: string): {
  type: "doc";
  content: Array<{ type: "paragraph"; content?: Array<{ type: "text"; text: string }> }>;
} {
  const blocks = String(plain ?? "").split(/\r?\n\r?\n/);
  return {
    type: "doc",
    content: blocks.map((block) => {
      const trimmed = block.replace(/\r?\n/g, " ").trim();
      if (!trimmed) return { type: "paragraph" } as const;
      return { type: "paragraph", content: [{ type: "text", text: trimmed }] } as const;
    }),
  };
}

export default function ChapterReviewEditor({
  initialDoc,
  busy,
  manuscriptSurface = false,
  onChange,
}: ChapterReviewEditorProps) {
  // Build the initial doc once so React 18 StrictMode double-mount doesn't
  // produce two different starting documents (and surprise `setEdited(true)`).
  const doc = useMemo(() => toProseMirrorDoc(initialDoc), [initialDoc]);

  const editorClass = manuscriptSurface
    ? "chapter-review-editor chapter-review-editor--manuscript prose-manuscript font-body text-lg leading-[1.85] text-[#2a221a]/95 focus:outline-none"
    : "chapter-review-editor prose-manuscript font-body text-lg leading-[1.8] text-on-surface/90 focus:outline-none";

  const editor = useEditor({
    extensions: [Document, Paragraph, Text, HardBreak],
    content: doc,
    editable: !busy,
    editorProps: {
      attributes: {
        class: editorClass,
        spellCheck: "false",
      },
    },
    onUpdate({ editor: ed }) {
      const text = ed.getText({ blockSeparator: "\n\n" });
      onChange(text);
    },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!busy);
  }, [editor, busy]);

  useEffect(() => {
    if (!editor) return;
    editor.setOptions({
      editorProps: {
        attributes: {
          class: editorClass,
          spellCheck: "false",
        },
      },
    });
  }, [editor, editorClass]);

  // No dependency array updates from initialDoc by design: TipTap owns the
  // document after first mount; the parent should remount via `key=runId` if
  // the source draft changes (e.g. user clicks Rerun and we re-enter review).

  return <EditorContent editor={editor} />;
}
