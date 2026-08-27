"use client";

import React, { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { useDispatch, useSelector } from "react-redux";

import { OverlayLoader } from "@/components/ui/overlay-loader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RootState, store } from "@/store/store";
import { setOutlines, setPresentationId } from "@/store/slices/presentationGeneration";
import {
  limitOutlines,
  trimTextToWordLimit,
} from "@/utils/presentationLimits";

import Chat from "../../presentation/components/Chat";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { Sparkles } from "lucide-react";
import { useOutlineManagement } from "../hooks/useOutlineManagement";
import { useOutlineStreaming } from "../hooks/useOutlineStreaming";
import EmptyStateView from "./EmptyStateView";
import OutlineContent from "./OutlineContent";
import OutlineStandardHeader from "./OutlineStandardHeader";
import TemplateSelection from "./TemplateSelection";

const getOutlinesFromResponse = (outline: unknown): { content: string }[] => {
  if (!outline || typeof outline !== "object") {
    return [];
  }

  const slides = (outline as { slides?: unknown }).slides;
  if (!Array.isArray(slides)) {
    return [];
  }

  return limitOutlines(
    slides.map((slide) => {
      const content =
        slide && typeof slide === "object"
          ? (slide as { content?: unknown }).content
          : null;

      if (typeof content === "string") {
        return { content };
      }
      if (content == null) {
        return { content: "" };
      }
      return { content: String(content) };
    })
  );
};

const scrollToPageTop = () => {
  window.requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  });
};

const buildSmartOutlinePrompt = (outlines: { content: string }[]) =>
  [
    "Create a polished presentation from this approved slide-by-slide outline.",
    "Treat every outline item as mandatory: do not remove, merge, reorder, or replace slides.",
    "Use the outline content as the source for each slide's copy, narrative, and visuals.",
    "",
    "Approved outline:",
    ...outlines.map((outline, index) => `Slide: ${index + 1}\n${outline.content}`),
  ].join("\n\n");

const OutlinePage: React.FC = () => {
  const dispatch = useDispatch();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { presentation_id: storedPresentationId, outlines } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  const queryPresentationId = searchParams.get("id")?.trim() || null;
  const suggestedTemplate = searchParams.get("template")?.trim() || null;
  const autoStart = searchParams.get("autostart") === "true";
  const presentation_id = queryPresentationId || storedPresentationId;
  // The frontend's Generate Outlines action deliberately bypasses template
  // selection. Normal outline routes still begin with the template chooser.
  const [isTemplateStage, setIsTemplateStage] = useState(!autoStart);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    null
  );
  const [hasOutlineStreamFinished, setHasOutlineStreamFinished] =
    useState(false);
  const [hasAutoStarted, setHasAutoStarted] = useState(false);
  const [isStartingSmartDeck, setIsStartingSmartDeck] = useState(false);

  const hasSelectedTemplate = selectedTemplateId !== null;
  const streamState = useOutlineStreaming(
    presentation_id,
    !isTemplateStage && (hasSelectedTemplate || autoStart)
  );
  const { handleDragEnd, handleAddSlide } = useOutlineManagement(outlines);

  const outlineControlsBusy =
    streamState.isLoading || streamState.isStreaming;
  const isOutlineReady =
    hasOutlineStreamFinished && !outlineControlsBusy && outlines.length > 0;
  const isOutlineAssistantVisible = !isTemplateStage && hasSelectedTemplate;
  const outlineStreamFinished =
    !isTemplateStage &&
    !outlineControlsBusy &&
    (outlines.length > 0 || streamState.statusMessage === "Outline ready");

  useEffect(() => {
    if (queryPresentationId && queryPresentationId !== storedPresentationId) {
      dispatch(setPresentationId(queryPresentationId));
    }
  }, [dispatch, queryPresentationId, storedPresentationId]);

  useEffect(() => {
    setHasOutlineStreamFinished(false);
    setHasAutoStarted(false);
  }, [presentation_id]);

  // The dedicated outline flow has already created a presentation record.
  // Enter the outline view immediately so its EventSource connects to
  // /api/v1/ppt/outlines/stream/{presentationId} and starts generation.
  useEffect(() => {
    if (!autoStart || hasAutoStarted) {
      return;
    }

    setHasAutoStarted(true);
    setIsTemplateStage(false);
    scrollToPageTop();
  }, [autoStart, hasAutoStarted]);

  useEffect(() => {
    if (!presentation_id || (!hasSelectedTemplate && !autoStart)) {
      setHasOutlineStreamFinished(false);
      return;
    }

    if (outlineStreamFinished) {
      setHasOutlineStreamFinished(true);
    }
  }, [autoStart, hasSelectedTemplate, outlineStreamFinished, presentation_id]);

  const handleReturnToTemplates = () => {
    if (streamState.isStreaming) return;
    setIsTemplateStage(true);
    scrollToPageTop();
  };

  const handleTemplateSelect = useCallback(
    (template: {
      id: string;
      name: string;
      source: "default" | "custom";
      position: number;
    }) => {
      setSelectedTemplateId(template.id);
      setIsTemplateStage(false);
      scrollToPageTop();
    },
    []
  );

  const handleUpdateOutline = (index: number, newContent: string) => {
    const slideIndex = index - 1;
    if (!outlines[slideIndex]) return;

    const limitedContent = trimTextToWordLimit(newContent);
    if (outlines[slideIndex].content === limitedContent) return;

    const updatedOutlines = [...outlines];
    updatedOutlines[slideIndex] = {
      ...updatedOutlines[slideIndex],
      content: limitedContent,
    };
    dispatch(setOutlines(updatedOutlines));
  };

  const handleOutlineChanged = useCallback(async () => {
    if (!presentation_id) {
      return;
    }

    const outline = await PresentationGenerationApi.getOutlines(presentation_id);
    dispatch(setOutlines(getOutlinesFromResponse(outline)));
  }, [dispatch, presentation_id]);

  const handleBeforeOutlineChatSend = useCallback(async () => {
    if (!presentation_id) {
      return;
    }

    const latestOutlines =
      store.getState().presentationGeneration.outlines;
    await PresentationGenerationApi.updateOutlines(
      presentation_id,
      latestOutlines
    );
  }, [presentation_id]);

  const handleSmartGeneration = useCallback(
    async (useEandTemplate: boolean) => {
      const approvedOutlines = store.getState().presentationGeneration.outlines;
      if (!isOutlineReady || isStartingSmartDeck || approvedOutlines.length === 0) {
        return;
      }

      setIsStartingSmartDeck(true);
      try {
        if (presentation_id) {
          await PresentationGenerationApi.updateOutlines(
            presentation_id,
            approvedOutlines
          );
        }

        const smartPresentation = await PresentationGenerationApi.createPresentation({
          content: buildSmartOutlinePrompt(approvedOutlines),
          // The e& template supplies a fixed title and thank-you slide. Leaving
          // the count automatic lets the backend reserve both around every
          // approved outline item.
          n_slides: useEandTemplate ? null : approvedOutlines.length,
          language: "English",
          include_title_slide: true,
          include_table_of_contents: false,
          generation_mode: "smart",
          smart_template: useEandTemplate ? "eand" : undefined,
        });

        dispatch(setPresentationId(smartPresentation.id));
        router.replace(
          `/presentation?id=${smartPresentation.id}&stream=true&type=smart`
        );
      } catch (error) {
        console.error("Failed to start Smart presentation generation", error);
        setIsStartingSmartDeck(false);
      }
    },
    [dispatch, isOutlineReady, isStartingSmartDeck, presentation_id, router]
  );

  if (!presentation_id) {
    return (
      <div className="min-h-screen bg-[#FEFEFF]">
        <OutlineStandardHeader
          title="Outline Generation"
          onBack={() => router.push("/")}
        />
        <EmptyStateView />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "min-h-screen overflow-x-clip font-syne",
        isTemplateStage ? "bg-white" : "bg-[#F3F6FA]"
      )}
    >
      <OverlayLoader
        show={isStartingSmartDeck}
        text="Starting Smart presentation..."
        showProgress
        duration={30}
      />

      <OutlineStandardHeader
        title={isTemplateStage ? "Select Template" : "Outline Generation"}
        slideCount={isTemplateStage ? undefined : outlines.length}
        onBack={() => {
          if (isTemplateStage) {
            router.push("/");
            return;
          }
          handleReturnToTemplates();
        }}
      />

      {isTemplateStage ? (
        <main className="mx-auto w-full max-w-[1440px] px-5 pb-12 pt-10 sm:px-10 lg:px-20">
          <TemplateSelection
            presentationId={presentation_id}
            selectedTemplateId={selectedTemplateId}
            suggestedTemplate={suggestedTemplate}
            onSuggestedTemplateResolved={(template) =>
              setSelectedTemplateId((current) => current ?? template.id)
            }
            onSelectTemplate={handleTemplateSelect}
          />
        </main>
      ) : (
        <>
          <div className="lg:mr-[369px]">
            <main className="mx-auto w-[calc(100%-2.5rem)] max-w-[967px] pb-28 pt-7 sm:w-[calc(100%-5rem)] sm:pt-9">
              <div>
                <OutlineContent
                  outlines={outlines}
                  isLoading={streamState.isLoading}
                  isStreaming={streamState.isStreaming}
                  activeSlideIndex={streamState.activeSlideIndex}
                  highestActiveIndex={streamState.highestActiveIndex}
                  statusMessage={streamState.statusMessage}
                  onDragEnd={handleDragEnd}
                  onAddSlide={handleAddSlide}
                  onUpdateOutline={handleUpdateOutline}
                />
              </div>
            </main>
          </div>

          {isOutlineAssistantVisible && (
            <aside className="mx-auto mb-28 mt-8 flex h-[600px] w-[calc(100%-2.5rem)] overflow-hidden border border-[#D9E0EA] bg-white sm:w-[calc(100%-5rem)] lg:fixed lg:bottom-0 lg:right-0 lg:top-[68px] lg:z-40 lg:mx-0 lg:mb-0 lg:mt-0 lg:h-auto lg:w-[369px] lg:border-0">
              <nav
                className="flex w-[70px] shrink-0 flex-col items-center gap-5 px-1.5 py-2"
                aria-label="Outline tools"
              >
                <div className="flex w-full flex-col items-center rounded-[10px] bg-[#FFF2F3] py-7">
                  <div className="flex rounded-[10px] border border-[#F2CDD1] bg-white p-1.5 shadow-[0_6.6px_6.6px_rgba(227,6,19,0.14)]">
                    <Image
                      src="/ai-star.svg"
                      alt=""
                      width={19}
                      height={18}
                      className="h-[18px] w-[19px]"
                    />
                  </div>
                  <span className="mt-1 text-xs font-normal text-[#E30613]">
                    AI
                  </span>
                </div>
                <span
                  className="h-px w-[30px] bg-[#EDEEEF]"
                  aria-hidden="true"
                />
              </nav>

              <div className="min-w-0 flex-1">
                <Chat
                  key={presentation_id}
                  presentationId={presentation_id}
                  variant="outline"
                  useEditorLayout
                  inputDisabled={!isOutlineReady}
                  onBeforeSend={handleBeforeOutlineChatSend}
                  onPresentationChanged={handleOutlineChanged}
                />
              </div>
            </aside>
          )}

          <div className="pointer-events-none fixed bottom-6 left-5 right-5 z-50 flex justify-center sm:left-10 sm:right-10 lg:left-0 lg:right-[369px]">
            <div className="pointer-events-auto">
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  disabled={!isOutlineReady || isStartingSmartDeck}
                  onClick={() => handleSmartGeneration(true)}
                  className="h-11 w-full rounded-lg bg-[#E30613] px-5 text-sm font-semibold text-white shadow-[0_6px_16px_rgba(227,6,19,.22)] hover:bg-[#B50510] sm:w-auto"
                >
                  <Sparkles size={16} />
                  Generate e&amp; presentation
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default OutlinePage;
