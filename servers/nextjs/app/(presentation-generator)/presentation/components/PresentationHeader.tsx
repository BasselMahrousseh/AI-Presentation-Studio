"use client";
import { Button } from "@/components/ui/button";
import {
  Play,
  Loader2,
  Redo2,
  Undo2,
  ArrowRightFromLine,
  ArrowUpRight,
  Pencil,
  Check,
  Keyboard,
  X,
} from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useRouter, usePathname } from "next/navigation";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useDispatch, useSelector } from "react-redux";

import { RootState } from "@/store/store";
import { notify } from "@/components/ui/sonner";
import {
  trackEvent,
  trackEventImmediately,
  MixpanelEvent,
} from "@/utils/mixpanel";
import { usePresentationUndoRedo } from "../hooks/PresentationUndoRedo";
import ToolTip from "@/components/ToolTip";
import { setEnableHtmlSelector, updateTitle } from "@/store/slices/presentationGeneration";
import MarkdownRenderer from "@/components/MarkDownRender";
import { cn } from "@/lib/utils";
import { KeyboardShortcutsDialog } from "./KeyboardShortcutsDialog";
import { sanitizeAnalyticsError } from "@/utils/analytics";
import { v4 as uuidv4 } from "uuid";
import { getStreamProgressLabel } from "../utils/streamProgressLabel";
import { ApiResponseHandler } from "../../services/api/api-error-handler";

const MAX_EXPORT_TITLE_LENGTH = 40;

const buildSafeExportFileName = (
  rawTitle: string | null | undefined,
  extension: "pdf" | "pptx"
) => {
  const normalizedTitle = (rawTitle || "presentation").trim();
  const titleWithoutExtension = normalizedTitle.replace(/\.(pdf|pptx)$/i, "");

  let safeBase = titleWithoutExtension
    // Replace all punctuation/special chars (including dots) with dashes
    .replace(/[^a-zA-Z0-9\s_-]+/g, "-")
    // Replace whitespace with single dashes
    .replace(/\s+/g, "-")
    // Collapse repeated separators
    .replace(/[-_]{2,}/g, "-")
    // Trim separators from both ends
    .replace(/^[-_]+|[-_]+$/g, "");

  if (!safeBase) {
    safeBase = "presentation";
  }

  if (safeBase.length > MAX_EXPORT_TITLE_LENGTH) {
    safeBase = safeBase
      .slice(0, MAX_EXPORT_TITLE_LENGTH)
      .replace(/[-_]+$/g, "");
  }

  if (!safeBase) {
    safeBase = "presentation";
  }

  return `${safeBase}.${extension}`;
};

const PresentationHeader = ({
  presentation_id,
  isPresentationSaving,
  currentSlide,
  generationMode = "standard",
  flushAutoSave,
}: {
  presentation_id: string;
  isPresentationSaving: boolean;
  currentSlide?: number;
  generationMode?: "standard" | "smart";
  /**
   * Forces the editor's debounced autosave to complete before export starts.
   * PPTX/PDF export reads the presentation from the database, not from the
   * editor's live state (see PdfMakerPage.tsx) - without this, an edit made
   * just before clicking Export could ship the file with the pre-edit
   * content, silently, since the debounce window (2s) can still be open.
   */
  flushAutoSave?: () => Promise<void>;
}) => {
  const [open, setOpen] = useState(false);
  const [shortcutsDialogOpen, setShortcutsDialogOpen] = useState(false);
  const router = useRouter();
  const [isExporting, setIsExporting] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const titleInputRef = useRef<HTMLInputElement>(null);
  /** Avoid committing on blur when Save/Cancel was used (focus/click ordering) */
  const titleBlurIntentRef = useRef<"none" | "save" | "cancel">("none");

  const pathname = usePathname();
  const dispatch = useDispatch();

  const {
    presentationData,
    isStreaming,
    streamTotalSlides,
    streamGeneratedSlides,
    streamStageMessage,
  } = useSelector((state: RootState) => state.presentationGeneration);

  const slidesGenerated = presentationData?.slides?.length ?? 0;
  const streamProgressLabel = getStreamProgressLabel({
    isStreaming,
    streamTotalSlides,
    streamGeneratedSlides,
    streamStageMessage,
    slidesGenerated,
  });
  const { onUndo, onRedo, canUndo, canRedo } = usePresentationUndoRedo();

  useEffect(() => {
    if (isEditingTitle) {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    }
  }, [isEditingTitle]);

  useEffect(() => {
    if (generationMode !== "smart" || isStreaming) {
      dispatch(setEnableHtmlSelector(false));
      return;
    }
    // Object selection stays available even though the header toggle is hidden.
    dispatch(setEnableHtmlSelector(true));
  }, [dispatch, generationMode, isStreaming]);

  const beginTitleEdit = () => {
    if (isStreaming || !presentationData) return;
    setDraftTitle(presentationData.title || "");
    setIsEditingTitle(true);
  };

  const commitTitleEdit = () => {
    if (!presentationData) {
      setIsEditingTitle(false);
      return;
    }
    const trimmed = draftTitle.trim();
    const next = trimmed || presentationData.title || "Presentation";
    if (next !== presentationData.title) {
      dispatch(updateTitle(next));
      trackEvent(MixpanelEvent.Presentation_Title_Updated, {
        pathname,
        presentation_id,
        previous_title_length: (presentationData.title || "").length,
        next_title_length: next.length,
      });
    }
    setIsEditingTitle(false);
  };

  const cancelTitleEdit = () => {
    setDraftTitle(presentationData?.title || "");
    setIsEditingTitle(false);
  };

  const handleTitleBlur = () => {
    queueMicrotask(() => {
      const intent = titleBlurIntentRef.current;
      titleBlurIntentRef.current = "none";
      if (intent === "cancel" || intent === "save") return;
      commitTitleEdit();
    });
  };

  const onTitleSaveMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    titleBlurIntentRef.current = "save";
  };

  const onTitleCancelMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    titleBlurIntentRef.current = "cancel";
  };

  const exportViaIpc = async (
    format: "pptx" | "pdf",
    title: string
  ): Promise<void> => {
    if (!window.electron?.exportPresentation) {
      throw new Error("Electron export bridge is unavailable");
    }
    const result = await window.electron.exportPresentation(
      presentation_id,
      title,
      format
    );
    if (!result?.success) {
      throw new Error(result?.message || "Export failed");
    }
  };

  const handleExportPptx = async () => {
    if (isStreaming) return;

    const exportId = uuidv4();
    const exportStartedAt = Date.now();
    const exportRuntime = window.electron?.exportPresentation
      ? "electron"
      : "browser_api";
    let exportToastId: string | number | undefined;
    try {
      exportToastId = notify.loading(
        "Exporting PPTX",
        "Your presentation is being exported. This may take a moment."
      );
      setIsExporting(true);
      // Must happen before the export request is built, for both the
      // electron and browser_api runtimes - a just-made edit is just as
      // real either way.
      await flushAutoSave?.();
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Started,
        "pptx",
        exportRuntime,
        exportId,
        exportStartedAt
      );
      const safePptxFileName = buildSafeExportFileName(
        presentationData?.title,
        "pptx"
      );
      const safePptxTitle = safePptxFileName.replace(/\.pptx$/i, "");
      if (exportRuntime === "electron") {
        await exportViaIpc("pptx", safePptxTitle);
      } else {
        const response = await fetch("/api/export-presentation", {
          method: "POST",
          body: JSON.stringify({
            format: "pptx",
            id: presentation_id,
            title: safePptxTitle,
          }),
        });

        // The route reports the REAL cause on failure - e.g. "Cannot find
        // module 'sharp'" or "presentation-export runtime is not available" -
        // in its JSON body (`{ error, success: false }`). Discarding that
        // and throwing a fixed "Failed to export PPTX" (the previous
        // behavior) meant every export failure showed the user the same
        // generic toast regardless of cause, so a real infra problem looked
        // identical to a transient one. ApiResponseHandler is the existing
        // shared parser for exactly this response shape.
        const { path: pptxPath } = await ApiResponseHandler.handleResponse(
          response,
          "Failed to export PPTX"
        );
        if (!pptxPath) {
          throw new Error("No path returned from export");
        }

        downloadLink(pptxPath, safePptxFileName);
      }
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Completed,
        "pptx",
        exportRuntime,
        exportId,
        exportStartedAt
      );
      notify.success(
        "Export complete",
        "Your PPTX file has been downloaded.",
        { id: exportToastId }
      );
    } catch (error) {
      console.error("Export failed:", error);
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Failed,
        "pptx",
        exportRuntime,
        exportId,
        exportStartedAt,
        error
      );
      notify.error(
        "Export failed",
        error instanceof Error && error.message
          ? error.message
          : "We are having trouble exporting your presentation. Please try again.",
        exportToastId !== undefined ? { id: exportToastId } : undefined
      );
    } finally {
      setIsExporting(false);
    }
  };

  const handleExportPdf = async () => {
    if (isStreaming) return;

    const exportId = uuidv4();
    const exportStartedAt = Date.now();
    const exportRuntime = window.electron?.exportPresentation
      ? "electron"
      : "browser_api";
    let exportToastId: string | number | undefined;
    try {
      exportToastId = notify.loading(
        "Exporting PDF",
        "Your presentation is being exported. This may take a moment."
      );
      setIsExporting(true);
      // Must happen before the export request is built, for both the
      // electron and browser_api runtimes - a just-made edit is just as
      // real either way.
      await flushAutoSave?.();
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Started,
        "pdf",
        exportRuntime,
        exportId,
        exportStartedAt
      );
      const safePdfFileName = buildSafeExportFileName(
        presentationData?.title,
        "pdf"
      );
      const safePdfTitle = safePdfFileName.replace(/\.pdf$/i, "");
      if (exportRuntime === "electron") {
        await exportViaIpc("pdf", safePdfTitle);
      } else {
        const response = await fetch("/api/export-presentation", {
          method: "POST",
          body: JSON.stringify({
            format: "pdf",
            id: presentation_id,
            title: safePdfTitle,
          }),
        });

        // See the matching comment in handleExportPptx above - same route,
        // same failure-message loss, same fix.
        const { path: pdfPath } = await ApiResponseHandler.handleResponse(
          response,
          "Failed to export PDF"
        );
        if (!pdfPath) {
          throw new Error("No path returned from export");
        }
        downloadLink(pdfPath, safePdfFileName);
      }
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Completed,
        "pdf",
        exportRuntime,
        exportId,
        exportStartedAt
      );
      notify.success(
        "Export complete",
        "Your PDF file has been downloaded.",
        { id: exportToastId }
      );
    } catch (error) {
      console.error(error);
      await trackExportLifecycle(
        MixpanelEvent.Presentation_Export_Failed,
        "pdf",
        exportRuntime,
        exportId,
        exportStartedAt,
        error
      );
      notify.error(
        "Export failed",
        error instanceof Error && error.message
          ? error.message
          : "We are having trouble exporting your presentation. Please try again.",
        exportToastId !== undefined ? { id: exportToastId } : undefined
      );
    } finally {
      setIsExporting(false);
    }
  };
  const downloadLink = (path: string, fileName: string) => {
    const link = document.createElement("a");
    link.href = path;
    link.download = fileName;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const trackExportLifecycle = async (
    event:
      | MixpanelEvent.Presentation_Export_Started
      | MixpanelEvent.Presentation_Export_Completed
      | MixpanelEvent.Presentation_Export_Failed,
    format: "pptx" | "pdf",
    exportRuntime: "electron" | "browser_api",
    exportId: string,
    exportStartedAt: number,
    error?: unknown
  ) => {
    try {
      await trackEventImmediately(event, {
        pathname,
        presentation_id,
        export_id: exportId,
        format,
        slide_count: presentationData?.slides?.length || 0,
        export_runtime: exportRuntime,
        generation_mode: generationMode,
        ...(event !== MixpanelEvent.Presentation_Export_Started
          ? { duration_ms: Date.now() - exportStartedAt }
          : {}),
        ...(error !== undefined
          ? { error_message: sanitizeAnalyticsError(error, "Export failed") }
          : {}),
      });
    } catch (analyticsError) {
      // Analytics must never prevent or change the result of an export.
      console.warn("Failed to track export lifecycle:", analyticsError);
    }
  };

  const ExportOptions = ({ mobile }: { mobile: boolean }) => (
    <div
      className={` rounded-[18px] max-md:mt-4 ${mobile ? "" : "bg-white"}  p-5`}
    >
      <p className="text-sm font-medium text-[#19001F]">Export as</p>
      <div className="my-[18px] h-[1px] bg-[#E8E8E8]" />
      <div className="space-y-3">
        <Button
          onClick={() => {
            handleExportPdf();
            setOpen(false);
          }}
          variant="ghost"
          className={`  rounded-none px-0 w-full text-xs flex justify-start text-black hover:bg-transparent ${mobile ? "bg-white py-6 border-none rounded-lg" : ""
            }`}
        >
          PDF
          <ArrowUpRight className="w-3.5 h-3.5" />
        </Button>
        <Button
          onClick={() => {
            handleExportPptx();
            setOpen(false);
          }}
          variant="ghost"
          className={`w-full flex px-0 justify-start text-xs text-black hover:bg-transparent  ${mobile ? "bg-white py-6" : ""
            }`}
        >
          PPTX
          <ArrowUpRight className="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
  );

  const openPresentMode = () => {
    const to = `?id=${presentation_id}&mode=present&slide=${
      currentSlide || 0
    }${generationMode === "smart" ? "&type=smart" : ""}`;

    trackEvent(MixpanelEvent.Presentation_Mode_Entered, {
      pathname,
      presentation_id,
      slide_index: currentSlide || 0,
      slide_count: presentationData?.slides?.length || 0,
      generation_mode: generationMode,
    });
    trackEvent(MixpanelEvent.Navigation, { from: pathname, to });
    router.push(to);
  };

  const titleBlock = (
    <div
      className={cn(
        "min-w-0 max-w-[min(640px,calc(100vw-12rem))] flex-1 transition-[box-shadow] duration-200",
        isEditingTitle && "relative z-[60]"
      )}
    >
      {isEditingTitle ? (
        <div className="flex w-[min(450px,calc(100vw-10rem))] items-stretch gap-0.5 rounded-xl border border-[#f1caca] bg-white pl-3.5 pr-1 py-1 shadow-[0_8px_24px_rgba(120,24,24,0.10)] ring-2 ring-[#e60000]/10">
          <input
            ref={titleInputRef}
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                titleBlurIntentRef.current = "save";
                commitTitleEdit();
              } else if (e.key === "Escape") {
                e.preventDefault();
                titleBlurIntentRef.current = "cancel";
                cancelTitleEdit();
              }
            }}
            placeholder="Presentation title"
            className="min-w-0 flex-1 border-0 bg-transparent py-2 pr-2 font-syne text-sm font-semibold leading-tight text-[#172a5c] placeholder:text-[#172a5c]/35 outline-none focus:ring-0"
            aria-label="Presentation title"
          />
          <div className="flex shrink-0 items-center gap-0.5 border-l border-[#EDECEC] pl-1 ml-0.5">
            <ToolTip content="Save · Enter">
              <button
                type="button"
                onMouseDown={onTitleSaveMouseDown}
                onClick={commitTitleEdit}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[#e60000] transition-colors hover:bg-[#fff0f0]"
                aria-label="Save title"
              >
                <Check className="h-4 w-4" strokeWidth={2.25} />
              </button>
            </ToolTip>
            <ToolTip content="Cancel · Esc">
              <button
                type="button"
                onMouseDown={onTitleCancelMouseDown}
                onClick={cancelTitleEdit}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[#101323]/55 hover:bg-[#F6F6F9] hover:text-[#101323] transition-colors"
                aria-label="Cancel editing title"
              >
                <X className="h-4 w-4" strokeWidth={2.25} />
              </button>
            </ToolTip>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={beginTitleEdit}
          disabled={isStreaming || !presentationData}
          className={cn(
            "group/title flex w-full min-w-0 items-center gap-2.5 rounded-xl px-3 py-2 text-left -mx-3 transition-colors",
            "hover:bg-[#fff5f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e60000] focus-visible:ring-offset-2",
            "disabled:pointer-events-none disabled:opacity-100 disabled:hover:bg-transparent"
          )}
        >
          <h2 className="min-w-0 w-[min(460px,calc(100vw-14rem))] flex-1 font-syne text-sm font-semibold leading-snug text-[#172a5c]">
            <MarkdownRenderer
              content={presentationData?.title || "Presentation"}
              className="mb-0 min-w-0 overflow-hidden text-ellipsis line-clamp-1 text-sm text-[#172a5c] prose-p:my-0 prose-headings:my-0"
            />
          </h2>
          {presentationData && !isStreaming && (
            <Pencil
              className="h-3.5 w-3.5 shrink-0 text-[#172a5c]/40 transition-all duration-200 group-hover/title:text-[#e60000] opacity-80 sm:opacity-0 sm:group-hover/title:opacity-100 group-hover/title:opacity-100"
              aria-hidden
            />
          )}
        </button>
      )}
    </div>
  );

  return (
    <>
      <div className="sticky top-0 z-50 flex min-h-[66px] items-center justify-between gap-4 border-b border-[#ece9e9] bg-white px-5 py-2.5 font-syne shadow-[0_1px_10px_rgba(23,42,92,0.04)] md:px-6">
        <div className="flex min-w-0 items-center gap-4">
          <Image
            onClick={() => {
              router.push("/");
            }}
            src="/eand-logo.png"
            alt="e&"
            width={62}
            height={32}
            className="h-8 w-[62px] shrink-0 cursor-pointer object-contain object-left"
          />
          <span className="hidden h-6 w-px bg-[#e3e3e5] sm:block" />
          {presentationData && !isStreaming && !isEditingTitle ? (
            <ToolTip content="Rename presentation">{titleBlock}</ToolTip>
          ) : (
            titleBlock
          )}
         
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {streamProgressLabel && (
            <div className="hidden items-center gap-2 rounded-full bg-[#fff5f5] px-3 py-2 text-xs font-medium text-[#e60000] sm:flex">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {streamProgressLabel}
            </div>
          )}
          {isPresentationSaving && (
            <div className="hidden items-center gap-2 rounded-full bg-[#f4faf8] px-3 py-2 text-xs font-medium text-[#18735d] sm:flex">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Saving
            </div>
          )}

          <div className="hidden h-10 items-center rounded-full border border-[#e5e7eb] bg-[#fbfbfc] px-1 md:flex">
            <ToolTip content="Undo">
              <button
                type="button"
                disabled={!canUndo}
                onClick={onUndo}
                className="flex h-8 w-8 items-center justify-center rounded-full text-[#56627d] transition hover:bg-white hover:text-[#e60000] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="Undo"
              >
                <Undo2 className="h-4 w-4" />
              </button>
            </ToolTip>
            <ToolTip content="Redo">
              <button
                type="button"
                disabled={!canRedo}
                onClick={onRedo}
                className="flex h-8 w-8 items-center justify-center rounded-full text-[#56627d] transition hover:bg-white hover:text-[#e60000] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="Redo"
              >
                <Redo2 className="h-4 w-4" />
              </button>
            </ToolTip>
            <span className="mx-1 h-5 w-px bg-[#e4e5e8]" />
            <ToolTip content="Present">
              <button
                type="button"
                onClick={openPresentMode}
                disabled={
                  isStreaming ||
                  !presentationData?.slides ||
                  presentationData.slides.length === 0
                }
                className="flex h-8 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold text-[#172a5c] transition hover:bg-white hover:text-[#e60000] disabled:cursor-not-allowed disabled:opacity-35"
              >
                <Play className="h-3.5 w-3.5" fill="currentColor" />
                Present
              </button>
            </ToolTip>
          </div>
          
              {/* <button
                type="button"
                data-testid="html-selector-btn"
                onClick={toggleHtmlSelector}
                aria-pressed={enableHtmlSelector}
                className={cn(
                  "hidden h-[38px] items-center gap-2 rounded-xl border px-3 font-syne text-xs font-semibold shadow-sm transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6D5DFB] focus-visible:ring-offset-2 xl:inline-flex",
                  enableHtmlSelector
                    ? "border-[#CEC6FF] bg-[#F3F0FF] text-[#5141E5]"
                    : "border-[#E4E4E8] bg-white text-[#3D3D48] hover:border-[#D7D2F5] hover:bg-[#FAF9FF] hover:text-[#5141E5]"
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-lg transition-colors",
                    enableHtmlSelector
                      ? "bg-[#6D5DFB] text-white"
                      : "bg-[#F1EFFF] text-[#6553E8]"
                  )}
                >
                  <MousePointer2 className="h-3.5 w-3.5" strokeWidth={2} />
                </span>
                <span className="whitespace-nowrap">Select to edit</span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "ml-0.5 h-1.5 w-1.5 rounded-full transition-colors",
                    enableHtmlSelector ? "bg-[#6D5DFB]" : "bg-[#B8B8C2]"
                  )}
                />
              </button> */}
            {/* </ToolTip> */}
          
          {/* <div className="flex items-center gap-2 bg-[#F6F6F9] px-3.5 h-[38px] border border-[#EDECEC] rounded-[80px]">
            <ToolTip content="Regenerate Presentation">
              <button
                type="button"
                onClick={() => setIsRegenerateConfirmOpen(true)}
                className="group"
              >
                <RotateCcw className="w-3.5 h-3.5 text-[#101323] group-hover:text-[#5141e5] duration-300" />
              </button>
            </ToolTip>
            <Separator orientation="vertical" className="h-4" />
            <ToolTip content="Undo">
              <button
                disabled={!canUndo}
                className=" disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer group"
                onClick={() => {
                  onUndo();
                }}
              >
                <Undo2 className="w-3.5 h-3.5 text-[#101323] group-hover:text-[#5141e5] duration-300" />
              </button>
            </ToolTip>
            <Separator orientation="vertical" className="h-4" />
            <ToolTip content="Redo">
              <button
                disabled={!canRedo}
                className=" disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer group"
                onClick={() => {
                  onRedo();
                }}
              >
                <Redo2 className="w-3.5 h-3.5 text-[#101323] group-hover:text-[#5141e5] duration-300" />
              </button>
            </ToolTip>
            <Separator orientation="vertical" className="h-4 w-[2px]" />
            <ToolTip content="Present">
              <button
                onClick={() => {
                  const to = `?id=${presentation_id}&mode=present&slide=${
                    currentSlide || 0
                  }${generationMode === "smart" ? "&type=smart" : ""}`;
                  trackEvent(MixpanelEvent.Presentation_Mode_Entered, {
                    pathname,
                    presentation_id,
                    slide_index: currentSlide || 0,
                    slide_count: presentationData?.slides?.length || 0,
                    generation_mode: generationMode,
                  });
                  trackEvent(MixpanelEvent.Navigation, { from: pathname, to });
                  router.push(to);
                }}
                disabled={
                  isStreaming ||
                  !presentationData?.slides ||
                  presentationData?.slides.length === 0
                }
                className="cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed group"
              >
                <Play className="w-3.5 h-3.5 text-[#101323] group-hover:text-[#5141e5] duration-300" />
              </button>
            </ToolTip>
          </div> */}

        {generationMode === "standard" && (
          <ToolTip content="Keyboard shortcuts (?)">
            <button
              type="button"
              aria-label="Keyboard shortcuts"
              aria-haspopup="dialog"
              aria-expanded={shortcutsDialogOpen}
              aria-keyshortcuts="?"
              data-testid="keyboard-shortcuts-btn"
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#e5e7eb] bg-[#fbfbfc] text-[#56627d] transition-colors hover:border-[#f0b6b6] hover:bg-[#fff5f5] hover:text-[#e60000] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e60000] focus-visible:ring-offset-2"
              onClick={() => setShortcutsDialogOpen(true)}
            >
              <Keyboard
                aria-hidden="true"
                className="size-4"
                strokeWidth={1.8}
              />
            </button>
          </ToolTip>)}

          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
              <button
                className="flex h-10 items-center gap-2 rounded-full bg-brand px-4 text-sm font-semibold text-white shadow-[0_8px_18px_rgba(230,0,0,0.20)] transition-colors hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isExporting || isStreaming === true}
              >
                {isExporting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  "Export"
                )}{" "}
                <ArrowRightFromLine className="w-3.5 h-3.5" />
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className="w-[200px] space-y-2 rounded-2xl border-[#ece8e8] p-0 shadow-[0_16px_34px_rgba(23,42,92,0.14)]"
            >
              <ExportOptions mobile={false} />
            </PopoverContent>
          </Popover>
        </div>
      </div>
      <KeyboardShortcutsDialog
        open={shortcutsDialogOpen}
        onOpenChange={setShortcutsDialogOpen}
      />
      {/* <Dialog
        open={isRegenerateConfirmOpen}
        onOpenChange={setIsRegenerateConfirmOpen}
      >
        <DialogContent className="w-[360px] rounded-2xl border-0 p-0 shadow-2xl sm:max-w-[360px]">
          <DialogHeader className="items-center px-6 pb-4 pt-6 text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
              <AlertTriangle className="h-6 w-6 text-red-500" />
            </div>
            <DialogTitle className="text-lg font-semibold text-[#191919]">
              Regenerate Presentation?
            </DialogTitle>
            <DialogDescription className="text-sm leading-relaxed text-gray-500">
              This will replace the current slides with a newly generated
              version and clear undo history. Your current edits may be lost.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-row border-t border-gray-100 p-0 sm:space-x-0">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsRegenerateConfirmOpen(false)}
              className="h-auto flex-1 rounded-none rounded-bl-2xl px-4 py-3.5 text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-700"
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={handleReGenerate}
              className="h-auto flex-1 rounded-none rounded-br-2xl border-l border-gray-100 px-4 py-3.5 text-sm font-medium text-red-500 hover:bg-red-50 hover:text-red-600"
            >
              Regenerate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <KeyboardShortcutsDialog
        open={shortcutsDialogOpen}
        onOpenChange={setShortcutsDialogOpen}
      /> */}
    </>
  );
};

export default PresentationHeader;
