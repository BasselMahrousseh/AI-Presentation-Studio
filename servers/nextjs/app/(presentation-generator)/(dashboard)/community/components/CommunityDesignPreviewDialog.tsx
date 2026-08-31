"use client";

import { Loader2, Sparkles } from "lucide-react";

import SmartHtmlSlide from "@/app/(presentation-generator)/components/SmartHtmlSlide";
import {
  getCommunityPresentationAuthor,
  getCommunityPresentationTitle,
  type CommunityPresentation,
} from "@/app/(presentation-generator)/services/api/community";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface CommunityDesignPreviewDialogProps {
  presentation: CommunityPresentation | null;
  open: boolean;
  loading?: boolean;
  onOpenChange: (open: boolean) => void;
  onUseDesign: (presentation: CommunityPresentation) => void;
}

export default function CommunityDesignPreviewDialog({
  presentation,
  open,
  loading = false,
  onOpenChange,
  onUseDesign,
}: CommunityDesignPreviewDialogProps) {
  const title = presentation ? getCommunityPresentationTitle(presentation) : "Design preview";
  const slides = presentation?.slides?.filter((slide) => slide.trim()) ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] max-w-6xl gap-0 overflow-hidden border-[#e4e6eb] bg-[#fbfcfe] p-0">
        <DialogHeader className="border-b border-[#e7e9ee] bg-white px-6 py-5 pr-14">
          <DialogTitle className="truncate font-syne text-xl font-semibold text-[#172a5c]">
            {title}
          </DialogTitle>
          <DialogDescription className="font-manrope text-sm text-[#6e7687]">
            {presentation ? `Shared by ${getCommunityPresentationAuthor(presentation)}` : "Loading shared design"}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[calc(92dvh-150px)] overflow-y-auto bg-[#f2f5f9] p-5 sm:p-7">
          {loading ? (
            <div className="flex min-h-[360px] flex-col items-center justify-center gap-3 text-sm font-medium text-[#687186]">
              <Loader2 className="h-6 w-6 animate-spin text-[#e60000]" />
              Loading the complete design…
            </div>
          ) : slides.length > 0 ? (
            <div className="mx-auto space-y-5">
              {slides.map((slide, index) => (
                <div key={`${presentation?.id ?? "preview"}-${index}`} className="overflow-hidden rounded-xl border border-[#dde2ea] bg-white shadow-[0_8px_22px_rgba(23,42,92,0.10)]">
                  <div className="flex h-9 items-center border-b border-[#edf0f4] bg-white px-3 text-xs font-semibold text-[#697386]">
                    Slide {index + 1}
                  </div>
                  <div className="aspect-video w-full overflow-hidden">
                    <SmartHtmlSlide
                      executeScripts={false}
                      html={slide}
                      fonts={presentation?.fonts}
                      title={`${title} — slide ${index + 1}`}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-dashed border-[#ccd4df] bg-white px-6 text-center text-sm text-[#687186]">
              This shared presentation does not contain any previewable slides.
            </div>
          )}
        </div>

        {presentation && (
          <div className="flex items-center justify-between gap-4 border-t border-[#e7e9ee] bg-white px-5 py-4 sm:px-6">
            <span className="hidden text-xs text-[#778095] sm:inline">Use this design as a visual reference for your next deck.</span>
            <button
              type="button"
              onClick={() => onUseDesign(presentation)}
              className="ml-auto inline-flex h-10 items-center gap-2 rounded-full bg-[#e60000] px-4 text-sm font-semibold text-white shadow-[0_7px_18px_rgba(230,0,0,0.22)] transition hover:bg-[#bd0000] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e60000] focus-visible:ring-offset-2"
            >
              <Sparkles className="h-4 w-4" />
              Use this design
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
