interface StreamProgressLabelInput {
  isStreaming: boolean | null;
  streamTotalSlides: number | null;
  streamStageMessage: string | null;
  slidesGenerated: number;
}

/** Real, backend-reported status text for an in-progress generation stream — no fabricated numbers. */
export function getStreamProgressLabel({
  isStreaming,
  streamTotalSlides,
  streamStageMessage,
  slidesGenerated,
}: StreamProgressLabelInput): string | null {
  if (!isStreaming) return null;

  if (streamTotalSlides && streamTotalSlides > 0) {
    if (slidesGenerated === 0) {
      return streamStageMessage || `Preparing ${streamTotalSlides} slides`;
    }
    if (slidesGenerated < streamTotalSlides) {
      return `Generating slide ${slidesGenerated + 1} of ${streamTotalSlides}`;
    }
    return "Finishing up";
  }

  return streamStageMessage || "Generating presentation";
}
