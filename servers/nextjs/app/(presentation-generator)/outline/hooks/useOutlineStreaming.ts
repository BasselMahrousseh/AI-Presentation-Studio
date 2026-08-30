import { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { notify } from "@/components/ui/sonner";
import { setOutlines } from "@/store/slices/presentationGeneration";
import { jsonrepair } from "jsonrepair";
import { RootState } from "@/store/store";
import { getApiUrl } from "@/utils/api";
import { limitOutlines } from "@/utils/presentationLimits";
import {
  isChatGptAuthRequiredMessage,
  requestChatGptReauth,
} from "@/utils/chatgptAuth";

const MAX_STREAM_RETRIES = 3;
const STREAM_RETRY_DELAY_MS = 1_000;
const DEFAULT_STATUS_MESSAGE = "Preparing your presentation outline";

export const useOutlineStreaming = (
  presentationId: string | null,
  enabled = true
) => {
  const dispatch = useDispatch();
  const { outlines } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeSlideIndex, setActiveSlideIndex] = useState<number | null>(null);
  const [highestActiveIndex, setHighestActiveIndex] = useState<number>(-1);
  const [statusMessage, setStatusMessage] = useState(DEFAULT_STATUS_MESSAGE);
  const outlinesRef = useRef<{ content: string }[]>(outlines);
  const prevSlidesRef = useRef<{ content: string }[]>([]);
  const activeIndexRef = useRef<number>(-1);
  const highestIndexRef = useRef<number>(-1);

  useEffect(() => {
    outlinesRef.current = outlines;
  }, [outlines]);

  useEffect(() => {
    const resetStreamingState = (message = DEFAULT_STATUS_MESSAGE) => {
      setIsStreaming(false);
      setIsLoading(false);
      setActiveSlideIndex(null);
      setHighestActiveIndex(-1);
      setStatusMessage(message);
      prevSlidesRef.current = [];
      activeIndexRef.current = -1;
      highestIndexRef.current = -1;
    };

    if (!enabled || !presentationId || outlinesRef.current.length > 0) {
      resetStreamingState();
      return;
    }

    let eventSource: EventSource | null = null;
    let accumulatedChunks = "";
    let retryCount = 0;
    let isClosed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let outlinePublishTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingOutlineSlides: { content: string }[] | null = null;

    const closeEventSource = () => {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    };

    const clearRetryTimer = () => {
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
    };

    const clearPendingOutlinePublish = () => {
      if (outlinePublishTimer) {
        clearTimeout(outlinePublishTimer);
        outlinePublishTimer = null;
      }
      pendingOutlineSlides = null;
    };

    const publishPendingOutlines = () => {
      outlinePublishTimer = null;
      const slidesToPublish = pendingOutlineSlides;
      pendingOutlineSlides = null;
      if (slidesToPublish) {
        dispatch(setOutlines(slidesToPublish));
      }
    };

    const scheduleOutlinePublish = (slides: { content: string }[]) => {
      pendingOutlineSlides = slides;
      if (outlinePublishTimer) return;

      // Batch repaired JSON snapshots so React can paint between partial
      // outline updates instead of receiving a Redux update for every chunk.
      outlinePublishTimer = setTimeout(publishPendingOutlines, 75);
    };

    const scheduleRetry = (reason: string): boolean => {
      if (retryCount >= MAX_STREAM_RETRIES || isClosed) {
        return false;
      }

      retryCount += 1;
      const retryDelay = STREAM_RETRY_DELAY_MS * retryCount;
      console.warn(
        `Outline stream retry ${retryCount}/${MAX_STREAM_RETRIES}: ${reason}`
      );

      closeEventSource();
      clearRetryTimer();
      clearPendingOutlinePublish();
      accumulatedChunks = "";
      prevSlidesRef.current = [];
      activeIndexRef.current = -1;
      highestIndexRef.current = -1;
      setStatusMessage("Reconnecting to outline stream");

      retryTimer = setTimeout(() => {
        if (!isClosed) {
          openStream();
        }
      }, retryDelay);

      return true;
    };

    const openStream = () => {
      closeEventSource();
      eventSource = new EventSource(
        getApiUrl(`/api/v1/ppt/outlines/stream/${presentationId}`)
      );

      eventSource.addEventListener("response", (event) => {
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          if (!scheduleRetry("invalid SSE payload")) {
            resetStreamingState();
            notify.error(
              "Stream parse failed",
              "Failed to parse outline stream response."
            );
          }
          return;
        }

        switch (data.type) {
          case "status":
            if (data.status) {
              setStatusMessage(data.status);
            }
            break;

          case "chunk":
            accumulatedChunks += data.chunk;
            try {
              const repairedJson = jsonrepair(accumulatedChunks);
              const partialData = JSON.parse(repairedJson);

              if (partialData.slides) {
                const nextSlides: { content: string }[] =
                  limitOutlines(partialData.slides || []);
                try {
                  const prev = prevSlidesRef.current || [];
                  let changedIndex: number | null = null;
                  const maxLen = Math.max(prev.length, nextSlides.length);
                  for (let i = 0; i < maxLen; i++) {
                    const prevContent = prev[i]?.content;
                    const nextContent = nextSlides[i]?.content;
                    if (nextContent !== prevContent) {
                      changedIndex = i;
                    }
                  }
                  const prevActive = activeIndexRef.current;
                  let nextActive = changedIndex ?? prevActive;
                  if (nextActive < prevActive) {
                    nextActive = prevActive;
                  }

                  // A slide's content is updated many times while it is being
                  // streamed. Only publish state when the active slide itself
                  // changes; calling setState for every chunk can create an
                  // update cascade during a fast SSE response.
                  if (nextActive !== prevActive) {
                    activeIndexRef.current = nextActive;
                    setActiveSlideIndex(nextActive);
                  }

                  if (nextActive > highestIndexRef.current) {
                    highestIndexRef.current = nextActive;
                    setHighestActiveIndex(nextActive);
                  }

                  // jsonrepair can yield the same partial outline for several
                  // consecutive chunks. Avoid replacing the Redux array when
                  // the visible slide contents have not changed.
                  if (changedIndex === null) {
                    return;
                  }
                } catch {}

                prevSlidesRef.current = nextSlides;
                scheduleOutlinePublish(nextSlides);
                setIsLoading((wasLoading) => (wasLoading ? false : wasLoading));
              }
            } catch {
              // JSON is not complete yet, so keep accumulating chunks.
            }
            break;

          case "complete":
            try {
              const outlinesData: { content: string }[] =
                limitOutlines(data.presentation.outlines.slides);
              clearPendingOutlinePublish();
              dispatch(setOutlines(outlinesData));
              setIsStreaming(false);
              setIsLoading(false);
              setActiveSlideIndex(null);
              setHighestActiveIndex(-1);
              setStatusMessage("Outline ready");
              prevSlidesRef.current = outlinesData;
              activeIndexRef.current = -1;
              highestIndexRef.current = -1;
              isClosed = true;
              closeEventSource();
              clearRetryTimer();
              retryCount = 0;
            } catch {
              if (!scheduleRetry("failed to parse complete payload")) {
                resetStreamingState();
                notify.error("Parse failed", "Failed to parse presentation data.");
              }
            }
            accumulatedChunks = "";
            break;

          case "closing":
            resetStreamingState("Outline ready");
            isClosed = true;
            closeEventSource();
            clearRetryTimer();
            retryCount = 0;
            break;

          case "error":
            if (isChatGptAuthRequiredMessage(data.detail)) {
              resetStreamingState();
              closeEventSource();
              requestChatGptReauth({
                message: data.detail,
                source: "outline-stream",
              });
              break;
            }
            if (!scheduleRetry(data.detail || "server returned stream error")) {
              resetStreamingState();
              closeEventSource();
              notify.error(
                "Outline streaming failed",
                data.detail ||
                  "Failed to connect to the server. Please try again."
              );
            }
            break;
        }
      });

      eventSource.onerror = () => {
        if (!scheduleRetry("connection lost")) {
          resetStreamingState();
          closeEventSource();
          notify.error(
            "Connection failed",
            "Failed to connect to the server. Please try again."
          );
        }
      };
    };

    setStatusMessage(DEFAULT_STATUS_MESSAGE);
    setIsStreaming(true);
    setIsLoading(true);
    openStream();

    return () => {
      isClosed = true;
      closeEventSource();
      clearRetryTimer();
      clearPendingOutlinePublish();
    };
  }, [presentationId, dispatch, enabled]);

  return {
    isStreaming,
    isLoading,
    activeSlideIndex,
    highestActiveIndex,
    statusMessage,
  };
};
