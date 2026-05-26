import { type ChangeEvent, useRef, useState } from "react";
import { ConfirmModal } from "../../components/ConfirmModal";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  onExportProjectBundle?: () => void;
  onImportProjectBundle?: (jsonText: string) => Promise<void>;
  getImportBundlePreview?: (jsonText: string) => { storyLine: string; macroLine: string };
  disabled?: boolean;
  onBusy?: (busy: boolean) => void;
  onError?: (message: string) => void;
  className?: string;
};

export function ProjectBundleFileActions({
  onExportProjectBundle,
  onImportProjectBundle,
  getImportBundlePreview,
  disabled = false,
  onBusy,
  onError,
  className = "",
}: Props) {
  const { t } = useI18n();
  const importInputRef = useRef<HTMLInputElement>(null);
  const importPendingTextRef = useRef<string | null>(null);
  const [importConfirmOpen, setImportConfirmOpen] = useState(false);
  const [importPreview, setImportPreview] = useState<{
    storyLine: string;
    macroLine: string;
  } | null>(null);

  function cancelSetupImportFlow() {
    importPendingTextRef.current = null;
    setImportConfirmOpen(false);
    setImportPreview(null);
  }

  async function handleImportProjectBundleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onImportProjectBundle || !getImportBundlePreview) return;
    onError?.("");
    try {
      const text = await file.text();
      const { storyLine, macroLine } = getImportBundlePreview(text);
      importPendingTextRef.current = text;
      setImportPreview({ storyLine, macroLine });
      setImportConfirmOpen(true);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : t("setup.importFailed"));
      cancelSetupImportFlow();
    }
  }

  async function confirmSetupImportProjectBundle() {
    const text = importPendingTextRef.current;
    if (!text || !onImportProjectBundle) return;
    setImportConfirmOpen(false);
    setImportPreview(null);
    importPendingTextRef.current = null;
    onBusy?.(true);
    onError?.("");
    try {
      await onImportProjectBundle(text);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : t("setup.importFailed"));
    } finally {
      onBusy?.(false);
    }
  }

  if (!onExportProjectBundle && !onImportProjectBundle) return null;

  return (
    <div className={className}>
      <p className="font-label text-[10px] font-bold uppercase tracking-[0.25em] text-secondary">
        {t("setup.projectFiles")}
      </p>
      <input
        ref={importInputRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => void handleImportProjectBundleFile(e)}
      />
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          className="btn-secondary flex-1 justify-center"
          onClick={onExportProjectBundle}
          disabled={!onExportProjectBundle || disabled}
        >
          {t("setup.exportProjectJson")}
        </button>
        <button
          type="button"
          className="btn-secondary flex-1 justify-center"
          onClick={() => importInputRef.current?.click()}
          disabled={!onImportProjectBundle || disabled}
        >
          {t("setup.importProjectJson")}
        </button>
      </div>

      <ConfirmModal
        mount={typeof document !== "undefined" ? document.body : null}
        open={importConfirmOpen && importPreview !== null}
        danger
        title={t("app.confirm.importProjectTitle")}
        message={
          importPreview
            ? t("app.confirm.importProjectBody", undefined, {
                storyLine: importPreview.storyLine,
                macroLine: importPreview.macroLine,
              })
            : ""
        }
        confirmLabel={t("app.confirm.importProjectConfirm")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => void confirmSetupImportProjectBundle()}
        onCancel={cancelSetupImportFlow}
      />
    </div>
  );
}
