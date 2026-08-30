'use client'
import React from "react";
import Image from "next/image";

import { Card } from "@/components/ui/card";
import { DashboardApi } from "@/app/(presentation-generator)/services/api/dashboard";
import { Archive, AlertTriangle, Copy, EllipsisVertical, Loader2, Trash } from "lucide-react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { usePathname, useRouter } from "next/navigation";
import { notify } from "@/components/ui/sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import SlideScale from "@/app/(presentation-generator)/components/PresentationRender";
import {
  shouldRenderTemplateV2HtmlPreview,
  TemplateV2HtmlSlidePreview,
} from "@/app/(presentation-generator)/components/TemplateV2HtmlSlidePreview";
import MarkdownRenderer from "@/components/MarkDownRender";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";

export const PresentationCard = ({
  id,
  title,
  presentation,
  viewMode = "grid",
  onDeleted,
  onDuplicated
}: {
  id: string;
  title: string;
  presentation: any;
  viewMode?: "grid" | "list";
  onDeleted?: (presentationId: string) => void;
  onDuplicated?: (presentation: any) => void;
}) => {
  const router = useRouter();
  const pathname = usePathname();
  const [showDeleteDialog, setShowDeleteDialog] = React.useState(false);
  const [showActions, setShowActions] = React.useState(false);
  const [isDeleting, setIsDeleting] = React.useState(false);
  const [isDuplicating, setIsDuplicating] = React.useState(false);
  const isUnsupported = presentation?.version === "v1-standard";
  const presentationType =
    presentation?.type === "smart" || presentation?.generation_mode === "smart"
      ? "smart"
      : "standard";

  const handlePreview = (e: React.MouseEvent) => {
    e.preventDefault();
    if (isUnsupported) {
      notify.warning(
        "Unsupported presentation",
        "This deck was created in an older Presenton version. Downgrade to a compatible version to open it."
      );
      return;
    }
    trackEvent(MixpanelEvent.Dashboard_Presentation_Opened, {
      pathname,
      presentation_id: id,
      title_length: (title || "").length,
      slide_count: presentation?.slides?.length || 0,
      presentation_type: presentationType,
    });
    router.push(`/presentation?id=${id}&type=${presentationType}`);
  };


  const handleDelete = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    const response = await DashboardApi.deletePresentation(id);

    if (response?.success) {
      trackEvent(MixpanelEvent.Dashboard_Presentation_Deleted, {
        pathname,
        presentation_id: id,
        slide_count: presentation?.slides?.length || 0,
      });
      notify.success("Presentation deleted", "The presentation was removed from your dashboard.");
      setShowDeleteDialog(false);
      if (onDeleted) {
        onDeleted(id);
      }
    } else {
      notify.error("Could not delete presentation", response?.message || "Something went wrong while deleting the presentation.");
    }
    setIsDeleting(false);
  };

  const handleDuplicate = async () => {
    if (isDuplicating) return;
    setIsDuplicating(true);
    try {
      const duplicated = await DashboardApi.duplicatePresentation(id);
      trackEvent(MixpanelEvent.Dashboard_Presentation_Duplicated, {
        pathname,
        presentation_id: id,
        duplicate_presentation_id: duplicated?.id,
        slide_count: presentation?.slides?.length || 0,
      });
      notify.success("Presentation duplicated", "A copy was added to your dashboard.");
      onDuplicated?.(duplicated);
    } catch (error) {
      notify.error(
        "Could not duplicate presentation",
        error instanceof Error ? error.message : "Something went wrong while duplicating the presentation."
      );
    } finally {
      setIsDuplicating(false);
    }
  };
  const firstSlide = presentation?.slides?.[0];
  const useTemplateV2HtmlPreview = shouldRenderTemplateV2HtmlPreview(
    firstSlide,
    presentation?.version
  );
  return (
    <>
      <Card
        suppressHydrationWarning={true}
        onClick={handlePreview}
        aria-disabled={isUnsupported}
        title={isUnsupported ? "Unsupported in this version of Presenton" : undefined}
        className={`relative flex flex-col overflow-hidden rounded-lg border border-[#e1e2e7] bg-white p-0 font-sans shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all duration-200 ${
          isUnsupported
            ? "cursor-not-allowed opacity-75"
            : "cursor-pointer hover:-translate-y-0.5 hover:border-[#efa5a5] hover:shadow-[0_8px_24px_rgba(84,32,32,0.12)]"
        }`}
      >
     
      <div
        id={`dashboard-presentation-card-${id}`}
        suppressHydrationWarning={true}
        className={`relative z-40 flex ${viewMode === "list" ? "min-h-[122px] flex-row" : "flex-col"}`}
      >
        {/* <p className=" text-xs font-syne absolute top-2 flex gap-1 capitalize  items-center left-2 rounded-[100px]  px-2.5 py-1 bg-[#3A3A3AF5] text-white font-semibold  z-40 ">

          {presentation.type}
        </p> */}

        <Image src="/card_bg.svg" alt="" fill sizes="(max-width: 640px) 100vw, (max-width: 1536px) 33vw, 20vw" className="pointer-events-none absolute left-0 top-0 h-full w-full object-cover opacity-[0.07]" />
        <div className={isUnsupported
          ? `relative flex aspect-video items-center justify-center overflow-hidden rounded-lg border border-[#EDEEEF] bg-white/90 ${viewMode === "list" ? "m-3 w-[170px] shrink-0" : "mx-5 mt-4"}`
          : `relative aspect-[1.72/1] overflow-hidden bg-[#f8f8fa] ${viewMode === "list" ? "m-3 w-[210px] shrink-0 rounded-md border border-[#e5e5e9]" : "w-full border-b border-[#ececf0]"}`
        }>

          {isUnsupported ? (
            <div className="flex flex-col items-center gap-2 px-5 text-center text-[#666666]">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F4F3FF] text-[#7A5AF8]">
                <Archive className="h-[18px] w-[18px]" aria-hidden="true" />
              </span>
              <p className="text-xs font-medium">Preview unavailable</p>
            </div>
          ) : useTemplateV2HtmlPreview ? (
            <TemplateV2HtmlSlidePreview
              slide={firstSlide}
              fonts={presentation.fonts}
            />
          ) : (
            <SlideScale
              slide={firstSlide}
              fonts={presentation.fonts}
              isClickable={false}
              presentationLayout={presentation.layout}
            />
          )}
        </div>
        <div className={`z-40 flex bg-white px-4 py-4 ${viewMode === "list" ? "min-w-0 flex-1 items-center" : "relative w-full"}`}>
          <div className="flex items-center justify-between gap-7 w-full">
            <div className="flex min-w-0 flex-col items-start gap-2">
              <div className="overflow-hidden text-[15px] font-semibold leading-5 text-[#18243d] line-clamp-2">
                <MarkdownRenderer content={title} className="mb-0 overflow-hidden font-sans text-[15px] font-semibold leading-5 text-[#18243d] line-clamp-2" />
              </div>
              <p className="text-xs font-medium text-[#7a8190]">
                Created {new Date(presentation?.created_at).toLocaleDateString()}
              </p>

            </div>
            <Popover open={showActions} onOpenChange={setShowActions}>
              <PopoverTrigger className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[#737b8c] transition-colors hover:bg-[#fff0f0] hover:text-[#d60000]" onClick={(e) => e.stopPropagation()}>
                <EllipsisVertical className="h-5 w-5" />
              </PopoverTrigger>
              <PopoverContent align="end" className="bg-white w-[200px]">
                {!isUnsupported && (
                  <button
                    className="flex items-center justify-between w-full px-2 py-1 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={isDuplicating}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setShowActions(false);
                      void handleDuplicate();
                    }}
                  >
                    <p>{isDuplicating ? "Duplicating..." : "Duplicate"}</p>
                    {isDuplicating ? (
                      <Loader2 className="h-4 w-4 animate-spin text-gray-500" />
                    ) : (
                      <Copy className="h-4 w-4 text-gray-500" />
                    )}
                  </button>
                )}
                <button
                  className="flex items-center justify-between w-full px-2 py-1 hover:bg-gray-100"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setShowActions(false);
                    setShowDeleteDialog(true);
                  }}
                >
                  <p>Delete</p>
                  <Trash className="h-4 w-4 text-red-500" />
                </button>
              </PopoverContent>
            </Popover>
          </div>

        </div>
      </div>
      </Card>

      <Dialog
        open={showDeleteDialog}
        onOpenChange={(open) => {
          if (isDeleting && !open) return;
          setShowDeleteDialog(open);
        }}
      >
        <DialogContent
          hideDefaultClose
          overlayClassName="z-[100] bg-[#101828]/55 backdrop-blur-[3px]"
          className="z-[101] w-[calc(100vw-32px)] max-w-[420px] gap-0 overflow-hidden rounded-[24px] border-0 bg-white p-0 font-syne shadow-[0_28px_90px_rgba(15,23,42,0.24)] sm:max-w-[420px]"
        >
          <DialogHeader className="items-center px-7 pb-6 pt-8 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#F4F3FF] ring-8 ring-[#FAF9FF]">
              <AlertTriangle
                className="h-6 w-6 text-[#7A5AF8]"
                strokeWidth={1.8}
                aria-hidden="true"
              />
            </div>
            <DialogTitle className="text-[22px] font-semibold leading-7 tracking-[-0.02em] text-[#191919]">
              Delete presentation?
            </DialogTitle>
            <DialogDescription asChild>
              <div className="w-full pt-2 text-sm leading-6 text-[#667085]">
                <p>This will permanently delete the presentation below.</p>
                <div
                  className="mt-4 rounded-[12px] border border-[#EAECF0] bg-[#F9FAFB] px-4 py-3 text-left"
                  title={title || "Untitled presentation"}
                >
                  <p className="line-clamp-2 break-words text-sm font-medium leading-5 text-[#344054]">
                    {title || "Untitled presentation"}
                  </p>
                </div>
                <p className="mt-3 text-[13px] text-[#98A2B3]">
                  This action cannot be undone.
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="grid grid-cols-2 gap-3 border-t border-[#EAECF0] bg-[#FCFCFD] p-4 sm:grid sm:space-x-0">
            <button
              type="button"
              onClick={() => setShowDeleteDialog(false)}
              disabled={isDeleting}
              className="h-11 rounded-[10px] border border-[#D0D5DD] bg-white px-4 text-sm font-medium text-[#344054] shadow-sm transition-colors hover:bg-[#F9FAFB] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7A5AF8]/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={isDeleting}
              className="flex h-11 items-center justify-center gap-2 rounded-[10px] bg-[#191919] px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#303030] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#7A5AF8]/30 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Deleting...
                </>
              ) : (
                <>
                  <Trash className="h-4 w-4" aria-hidden="true" />
                  Delete
                </>
              )}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};
