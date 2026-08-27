import React, { forwardRef, memo, useCallback } from "react";
import type { Slide } from "../../types/slide";
import { useNearViewport } from "@/app/hooks/useNearViewport";
import { V1ContentRender } from "../../components/V1ContentRender";
import SmartHtmlSlide from "../../components/SmartHtmlSlide";
import {
  shouldRenderTemplateV2HtmlPreview,
  TemplateV2HtmlSlidePreview,
} from "../../components/TemplateV2HtmlSlidePreview";

interface SlideThumbnailCardProps extends React.HTMLAttributes<HTMLDivElement> {
  slide: Slide;
  index: number;
  selected: boolean;
  fonts?: unknown;
  presentationVersion?: unknown;
}

// The sidebar is 196px wide; this keeps a 16:9 preview visually full-width.
const SCALE = 0.125;

const SlideThumbnailCardComponent = forwardRef<
  HTMLDivElement,
  SlideThumbnailCardProps
>(
  (
    {
      slide,
      index,
      selected,
      fonts,
      presentationVersion,
      className = "",
      style,
      ...props
    },
    ref
  ) => {
    const { isNearViewport, ref: setViewportRoot } =
      useNearViewport<HTMLDivElement>({
        forceActive: selected,
        rootMargin: "72px 0px",
        rootSelector: "[data-slide-thumbnail-scroll-container='true']",
      });
    const setRootRef = useCallback(
      (node: HTMLDivElement | null) => {
        setViewportRoot(node);
        if (typeof ref === "function") {
          ref(node);
        } else if (ref) {
          ref.current = node;
        }
      },
      [ref, setViewportRoot],
    );
    const useTemplateV2HtmlPreview = shouldRenderTemplateV2HtmlPreview(
      slide,
      presentationVersion
    );

    return (
      <div
        ref={setRootRef}
        data-slide-thumbnail-active={isNearViewport ? "true" : "false"}
        style={{
          backgroundColor: "var(--card-color, #ffffff)",
          borderColor: selected ? "#e60000" : "var(--stroke, #e5e7eb)",
          ...style,
        }}
        className={`relative cursor-pointer overflow-hidden rounded-xl border bg-white p-1.5 transition-all duration-200 ${
          selected
            ? "border-[#e60000] shadow-[0_6px_16px_rgba(230,0,0,0.16)]"
            : "border-[#e6e7eb] hover:border-[#f0b6b6] hover:shadow-sm"
        } ${className}`}
        {...props}
      >
        <p className={`pointer-events-none absolute -left-1 top-1/2 z-50 flex h-[18px] min-w-[18px] -translate-y-1/2 items-center justify-center rounded-full border px-1 text-[10px] font-semibold shadow-sm ${
          selected
            ? "border-[#e60000] bg-[#e60000] text-white"
            : "border-[#e6e7eb] bg-white text-[#172a5c]"
        }`}>
          {index + 1}
        </p>

        <div
          className="relative"
          style={{ height: `${720 * SCALE}px`, overflow: "hidden" }}
        >
          {!isNearViewport ? (
            <div
              className="absolute inset-0 rounded-[10px] bg-white"
              aria-hidden="true"
            />
          ) : typeof slide.html_content === "string" && slide.html_content.trim() ? (
            <div
              className="absolute left-0 top-0 pointer-events-none"
              style={{
                width: 1280,
                height: 720,
                transformOrigin: "top left",
                transform: `scale(${SCALE})`,
              }}
            >
              <SmartHtmlSlide
                fixedSize
                fonts={fonts}
                html={slide.html_content}
                title={`Slide ${index + 1} thumbnail`}
              />
            </div>
          ) : useTemplateV2HtmlPreview ? (
            <TemplateV2HtmlSlidePreview
              slide={slide}
              fonts={fonts}
              className="pointer-events-none rounded-[10px]"
            />
          ) : (
            <div
              className="absolute top-0 left-0 rounded-[10px] overflow-hidden pointer-events-none"
              style={{
                width: 1280,
                height: 720,
                transformOrigin: "top left",
                transform: `scale(${SCALE})`,
              }}
            >
              <V1ContentRender
                slide={slide}
                isEditMode={false}
                fonts={fonts}
              />
            </div>
          )}
        </div>
      </div>
    );
  }
);

SlideThumbnailCardComponent.displayName = "SlideThumbnailCard";

export const SlideThumbnailCard = memo(
  SlideThumbnailCardComponent,
  (previous, next) =>
    previous.slide === next.slide &&
    previous.index === next.index &&
    previous.selected === next.selected &&
    previous.fonts === next.fonts &&
    previous.presentationVersion === next.presentationVersion &&
    previous.className === next.className &&
    previous.style === next.style
);

SlideThumbnailCard.displayName = "Memo(SlideThumbnailCard)";
