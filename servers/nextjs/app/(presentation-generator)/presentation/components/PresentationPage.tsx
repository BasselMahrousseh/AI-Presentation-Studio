"use client";
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useDispatch, useSelector } from "react-redux";
import { v4 as uuidv4 } from "uuid";
import { RootState } from "@/store/store";
import "../../utils/prism-languages";
import { Skeleton } from "@/components/ui/skeleton";
import { OverlayLoader } from "@/components/ui/overlay-loader";
import PresentationMode from "./PresentationMode";
import SidePanel from "./SidePanel";
import SlideContent from "./SlideContent";
import { Button } from "@/components/ui/button";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { AlertCircle } from "lucide-react";
import {
  usePresentationStreaming,
  usePresentationData,
  usePresentationNavigation,
  useAutoSave,
} from "../hooks";
import { PresentationPageProps } from "../types";
import { applyPresentationThemeToElement } from "../utils/applyPresentationThemeDom";
import EandLightOverlay from "@/app/components/EandLightOverlay";
import { getStreamProgressLabel } from "../utils/streamProgressLabel";

import { replaceSlidesWithBlankFallback } from "@/store/slices/presentationGeneration";
import {
  createBlankPresentationSlide,
  getPresentationTemplateId,
  isTemplateV2Slide,
  isTemplateV2TemplateId,
} from "../../_shared/blank-slide";
import PresentationHeader from "./PresentationHeader";
import {
  TEMPLATE_V2_ACTIVATE_SURFACE_EVENT,
  TEMPLATE_V2_SURFACE_SELECTED_EVENT,
  type TemplateV2ActivateSurfaceDetail,
  type TemplateV2SurfaceSelectedDetail,
} from "@/components/slide-editor/events/events";

function hasTemplateV2Layouts(layout: unknown): boolean {
  if (!layout || typeof layout !== "object") return false;
  const layouts = (layout as any).layouts;
  if (Array.isArray(layouts)) return true;
  return Boolean(
    layouts &&
    typeof layouts === "object" &&
    Array.isArray((layouts as any).layouts)
  );
}

function hasTemplateV2Slides(slides: unknown): boolean {
  return (
    Array.isArray(slides) &&
    slides.some((slide) => isTemplateV2Slide(slide))
  );
}

function collectTemplateV2Ids(value: unknown): string[] {
  const ids = new Set<string>();
  const visit = (item: unknown, depth = 0) => {
    if (depth > 4 || !item) return;
    if (Array.isArray(item)) {
      item.forEach((entry) => visit(entry, depth + 1));
      return;
    }
    if (typeof item !== "object") return;
    const record = item as Record<string, unknown>;
    ["layout_group", "layout", "template_id", "templateV2Id", "template_v2_id", "id"].forEach(
      (key) => {
        const value = record[key];
        if (isTemplateV2TemplateId(value)) {
          ids.add(value);
        }
      }
    );
    visit(record.layout, depth + 1);
    visit(record.layouts, depth + 1);
    visit(record.slides, depth + 1);
  };
  visit(value);
  return Array.from(ids);
}

interface LoadingState {
  isLoading: boolean;
  message: string;
  showProgress: boolean;
  duration: number;
  indeterminateProgress?: boolean;
  extra_info?: string;
}

type SlideAddedOptions = {
  promptOverlaySlideId?: string;
  promptOverlayKind?: "blank" | "layout";
};

const DEFAULT_LOADING_STATE: LoadingState = {
  isLoading: true,
  message: "Loading presentation",
  showProgress: false,
  duration: 0,
  extra_info: "",
};

const STREAM_LOADING_STATE: LoadingState = {
  isLoading: true,
  message: "Creating your presentation",
  showProgress: true,
  duration: 90,
  indeterminateProgress: true,
  extra_info: "This can take a few minutes depending on slide count.",
};

const IDLE_LOADING_STATE: LoadingState = {
  isLoading: false,
  message: "",
  showProgress: false,
  duration: 0,
  extra_info: "",
};

const PresentationPage: React.FC<PresentationPageProps> = ({
  presentation_id,
}) => {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const dispatch = useDispatch();
  // State management
  const [loading, setLoading] = useState(true);
  const [loadingState, setLoadingState] =
    useState<LoadingState>(DEFAULT_LOADING_STATE);
  const [selectedSlide, setSelectedSlide] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [blankPromptSlideIds, setBlankPromptSlideIds] = useState<Set<string>>(
    () => new Set()
  );
  const [templatePromptSlideIds, setTemplatePromptSlideIds] = useState<
    Set<string>
  >(() => new Set());
  const [error, setError] = useState(false);
  const slidesScrollContainerRef = useRef<HTMLDivElement | null>(null);
  const templateV2EditorLoadedKeyRef = useRef<string | null>(null);
  const router = useRouter();
  const shouldPreloadTemplateV2Presentation =
    searchParams.get("editor") === "v2" || searchParams.get("type") === "smart";

  const { presentationData, isStreaming, streamTotalSlides, streamStageMessage } =
    useSelector((state: RootState) => state.presentationGeneration);
  const slidesLength = presentationData?.slides?.length ?? 0;
  const streamProgressLabel = getStreamProgressLabel({
    isStreaming,
    streamTotalSlides,
    streamStageMessage,
    slidesGenerated: slidesLength,
  });
  const isSmartPresentation =
    searchParams.get("type") === "smart" ||
    presentationData?.type === "smart" ||
    presentationData?.generation_mode === "smart";
  const isTemplateV2Presentation =
    presentationData?.version === "v2-standard" ||
    hasTemplateV2Layouts(presentationData?.layout) ||
    hasTemplateV2Slides(presentationData?.slides);
  const editingDisabled = isStreaming === true;

  const { isSaving } = useAutoSave({
    debounceMs: 2000,
    enabled: !!presentationData && !isStreaming,
  });

  // Custom hooks
  const { fetchUserSlides } = usePresentationData(
    presentation_id,
    setLoading,
    setError
  );

  const {
    isPresentMode,
    stream,
    currentSlide: presentSlideFromUrl,
    scrollToSlide,
    handleSlideClick,
    toggleFullscreen,
    handlePresentExit,
    handleSlideChange,
  } = usePresentationNavigation(
    presentation_id,
    selectedSlide,
    setSelectedSlide,
    setIsFullscreen
  );

  // Initialize streaming
  usePresentationStreaming(
    presentation_id,
    stream,
    setLoading,
    setError,
    fetchUserSlides,
    {
      preloadPresentationData: shouldPreloadTemplateV2Presentation,
      generationMode: isSmartPresentation ? "smart" : "standard",
    }
  );

  useEffect(() => {
    if (
      !presentationData ||
      loading ||
      error ||
      stream ||
      !isTemplateV2Presentation ||
      slidesLength > 0
    ) {
      return;
    }

    const blankSlide = createBlankPresentationSlide({
      id: uuidv4(),
      index: 0,
      presentationId: presentation_id,
      templateId: getPresentationTemplateId(presentationData),
      isTemplateV2: true,
    });
    dispatch(replaceSlidesWithBlankFallback({ slideData: blankSlide }));
    setSelectedSlide(0);
  }, [
    dispatch,
    error,
    isTemplateV2Presentation,
    loading,
    presentationData,
    presentation_id,
    slidesLength,
    stream,
  ]);

  useEffect(() => {
    if (!loading) {
      setLoadingState(IDLE_LOADING_STATE);
      return;
    }

    if (!stream) {
      setLoadingState(DEFAULT_LOADING_STATE);
      return;
    }

    setLoadingState({
      ...STREAM_LOADING_STATE,
      message: streamProgressLabel || STREAM_LOADING_STATE.message,
    });
  }, [loading, stream, streamProgressLabel]);

  useEffect(() => {
    if (!isStreaming) return;

    const scrollContainer = slidesScrollContainerRef.current;
    if (!scrollContainer) return;

    const frame = window.requestAnimationFrame(() => {
      if (slidesLength <= 1) {
        scrollContainer.scrollTo({ top: 0, behavior: "auto" });
        setSelectedSlide(0);
        return;
      }

      setSelectedSlide(slidesLength - 1);
      scrollToSlide(slidesLength - 1, 2, "smooth");
    });

    return () => window.cancelAnimationFrame(frame);
  }, [isStreaming, scrollToSlide, slidesLength]);

  useEffect(() => {
    trackEvent(MixpanelEvent.Presentation_Editor_Viewed, {
      pathname,
      presentation_id,
      stream_mode: !!stream,
      presentation_mode: isPresentMode ? "present" : "edit",
      generation_mode: isSmartPresentation ? "smart" : "standard",
    });
  }, [
    isPresentMode,
    isSmartPresentation,
    pathname,
    presentation_id,
    stream,
  ]);

  useEffect(() => {
    if (!presentationData || !isTemplateV2Presentation || loading || error) {
      return;
    }
    if (templateV2EditorLoadedKeyRef.current === presentation_id) {
      return;
    }
    templateV2EditorLoadedKeyRef.current = presentation_id;
    trackEvent(MixpanelEvent.TemplateV2_Editor_Loaded, {
      presentation_id,
      slide_count: slidesLength,
      stream_mode: !!stream,
      template_id_candidates: collectTemplateV2Ids(presentationData),
    });
  }, [
    error,
    isTemplateV2Presentation,
    loading,
    presentationData,
    presentation_id,
    slidesLength,
    stream,
  ]);

  /** Editor tree unmounts in present mode; remount loses inline theme CSS — re-apply from Redux. */
  useLayoutEffect(() => {
    if (isPresentMode) return;
    const theme = presentationData?.theme;
    if (!theme) return;
    const el = document.getElementById("presentation-slides-wrapper");
    applyPresentationThemeToElement(el, theme);
  }, [isPresentMode, presentationData?.theme]);

  const onSlideChange = (newSlide: number) => {
    handleSlideChange(newSlide, presentationData);
  };

  const handleEditorSlideNavigation = useCallback(
    (index: number, options?: SlideAddedOptions) => {
      handleSlideClick(index);
      if (!options?.promptOverlayKind || !options.promptOverlaySlideId) {
        return;
      }
      if (options.promptOverlayKind === "blank") {
        setBlankPromptSlideIds((current) => {
          const next = new Set(current);
          next.add(options.promptOverlaySlideId!);
          return next;
        });
        return;
      }
      if (options.promptOverlayKind === "layout") {
        setTemplatePromptSlideIds((current) => {
          const next = new Set(current);
          next.add(options.promptOverlaySlideId!);
          return next;
        });
      }
    },
    [handleSlideClick],
  );

  const dismissBlankPromptOverlay = useCallback((slideId: unknown) => {
    if (typeof slideId !== "string" || !slideId) return;
    setBlankPromptSlideIds((current) => {
      if (!current.has(slideId)) return current;
      const next = new Set(current);
      next.delete(slideId);
      return next;
    });
  }, []);

  const dismissTemplatePromptOverlay = useCallback((slideId: unknown) => {
    if (typeof slideId !== "string" || !slideId) return;
    setTemplatePromptSlideIds((current) => {
      if (!current.has(slideId)) return current;
      const next = new Set(current);
      next.delete(slideId);
      return next;
    });
  }, []);

  const totalSlides = presentationData?.slides?.length ?? 0;

  useEffect(() => {
    if (totalSlides <= 0 || selectedSlide <= totalSlides - 1) {
      return;
    }
    setSelectedSlide(totalSlides - 1);
  }, [selectedSlide, totalSlides]);

  useEffect(() => {
    const handleTemplateV2SurfaceSelected = (event: Event) => {
      const detail = (event as CustomEvent<TemplateV2SurfaceSelectedDetail>)
        .detail;
      const slideIndex = detail?.slideIndex;
      if (typeof slideIndex !== "number") return;
      if (slideIndex < 0 || slideIndex >= totalSlides) return;
      setSelectedSlide((current) =>
        current === slideIndex ? current : slideIndex
      );
    };

    window.addEventListener(
      TEMPLATE_V2_SURFACE_SELECTED_EVENT,
      handleTemplateV2SurfaceSelected
    );
    return () => {
      window.removeEventListener(
        TEMPLATE_V2_SURFACE_SELECTED_EVENT,
        handleTemplateV2SurfaceSelected
      );
    };
  }, [totalSlides]);

  useEffect(() => {
    if (
      isPresentMode ||
      !isTemplateV2Presentation ||
      typeof window === "undefined"
    ) {
      return;
    }
    delete document.documentElement.dataset.templateV2KonvaActiveSurface;
    delete document.documentElement.dataset.templateV2KonvaActiveSlideIndex;
    const frame = window.requestAnimationFrame(() => {
      window.dispatchEvent(
        new CustomEvent<TemplateV2ActivateSurfaceDetail>(
          TEMPLATE_V2_ACTIVATE_SURFACE_EVENT,
          {
            detail: {
              slideIndex: selectedSlide,
            },
          }
        )
      );
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isPresentMode, isTemplateV2Presentation, selectedSlide]);

  // Presentation Mode View
  if (isPresentMode) {
    return (
      <PresentationMode
        slides={presentationData?.slides!}
        currentSlide={presentSlideFromUrl}
        theme={presentationData?.theme ?? undefined}
        fonts={presentationData?.fonts}
        isFullscreen={isFullscreen}
        onFullscreenToggle={toggleFullscreen}
        onExit={handlePresentExit}
        onSlideChange={onSlideChange}
      />
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-gray-100 font-syne">
        <div
          className="bg-white border border-red-300 text-red-700 px-6 py-8 rounded-lg shadow-lg flex flex-col items-center"
          role="alert"
        >
          <AlertCircle className="w-16 h-16 mb-4 text-red-500" />
          <h2 className="text-xl font-semibold mb-2">Something went wrong</h2>
          <p className="text-center mb-4">
            We couldn't load your presentation. Please try again.
          </p>
          <div className="flex gap-2 justify-center items-center">
            <Button
              onClick={() => {
                trackEvent(
                  MixpanelEvent.PresentationPage_Refresh_Page_Button_Clicked,
                  { pathname }
                );
                window.location.reload();
              }}
            >
              Refresh Page
            </Button>
            <Button
              onClick={() => {
                trackEvent(MixpanelEvent.Navigation, {
                  from: pathname,
                  to: "/upload",
                });
                router.push("/upload");
              }}
            >
              Go to Upload
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="eand-presentation relative h-dvh overflow-hidden bg-[#f5f6f8] font-syne">
      <EandLightOverlay />
      <OverlayLoader
        show={loadingState.isLoading}
        text={loadingState.message}
        showProgress={loadingState.showProgress}
        duration={loadingState.duration}
        indeterminateProgress={loadingState.indeterminateProgress}
        extra_info={loadingState.extra_info}
      />
      <div
        id="presentation-slides-wrapper"
        className="relative z-10 flex h-full flex-col overflow-hidden"
      >
        <PresentationHeader
          presentation_id={presentation_id}
          isPresentationSaving={isSaving}
          currentSlide={selectedSlide}
          generationMode={isSmartPresentation ? "smart" : "standard"}
        />
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="sticky top-0 hidden h-full w-[196px] shrink-0 self-start border-r border-[#e7e5e5] bg-white md:block">
            <SidePanel
              selectedSlide={selectedSlide}
              onSlideClick={handleEditorSlideNavigation}
              presentationId={presentation_id}
              loading={loading}
            />
          </div>
          <div className="h-full w-full min-w-0 flex-1 p-4 md:p-6 2xl:pr-5">
            <div
              ref={slidesScrollContainerRef}
              data-presentation-slides-scroll-container="true"
              className="hide-scrollbar h-full overflow-y-auto scroll-pt-4 font-inter"
            >
              <div className="mx-auto flex min-h-full w-full max-w-[1280px] flex-col items-center pb-10">
                {!presentationData ||
                  loading ||
                  !presentationData?.slides ||
                  presentationData?.slides.length === 0 ? (
                  <div className="relative w-full h-[calc(100vh-120px)] mx-auto hide-scrollbar">
                    <div className="">
                      {Array.from({ length: 2 }).map((_, index) => (
                        <Skeleton
                          key={index}
                          className="aspect-video bg-gray-400 my-4 w-full mx-auto "
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <>
                    {presentationData &&
                      presentationData.slides &&
                      presentationData.slides.length > 0 &&
                      presentationData.slides.map(
                        (slide: any, index: number) => (
                          <SlideContent
                            key={
                              slide.id ??
                              `${slide.type ?? "slide"}-${slide.index ?? index}`
                            }
                            slide={slide}
                            index={index}
                            selected={selectedSlide === index}
                            presentationId={presentation_id}
                            onSlideActive={setSelectedSlide}
                            onSlideAdded={handleEditorSlideNavigation}
                            theme={presentationData?.theme}
                            fonts={presentationData?.fonts}
                            editingDisabled={editingDisabled}
                            isStreaming={isStreaming}
                            showBlankPromptOverlay={
                              typeof slide?.id === "string" &&
                              blankPromptSlideIds.has(slide.id)
                            }
                            onBlankPromptOverlayDismiss={() =>
                              dismissBlankPromptOverlay(slide?.id)
                            }
                            showTemplatePromptOverlay={
                              typeof slide?.id === "string" &&
                              templatePromptSlideIds.has(slide.id)
                            }
                            onTemplatePromptOverlayDismiss={() =>
                              dismissTemplatePromptOverlay(slide?.id)
                            }
                          />
                          // <div></div>
                        )
                      )}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PresentationPage;
