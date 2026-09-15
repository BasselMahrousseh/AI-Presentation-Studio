interface StreamProgressLabelInput {
  isStreaming: boolean | null;
  streamTotalSlides: number | null;
  /**
   * Slides the backend actually generates, when it reports them. The e& brand
   * template adds a fixed cover and thank-you slide on top of the generated
   * deck, but splices them in *after* generation instead of streaming them —
   * so counting them here made a 10-slide request report "slide 4 of 12",
   * against a total the user never asked for and never saw being generated.
   */
  streamGeneratedSlides?: number | null;
  streamStageMessage: string | null;
  slidesGenerated: number;
  /**
   * True while the stream's connection has dropped and a retry is pending
   * (see usePresentationStreaming's scheduleRetry). Checked before the
   * isStreaming gate below so a dropped connection during an otherwise
   * in-progress generation reads as "Reconnecting…" instead of silently
   * looking identical to a stall - see CLAUDE.md's "Next.js exited
   * cleanly" entry for why a connection can drop mid-generation.
   */
  isReconnecting?: boolean;
}

/** Real, backend-reported status text for an in-progress generation stream — no fabricated numbers. */
export function getStreamProgressLabel({
  isStreaming,
  streamTotalSlides,
  streamGeneratedSlides,
  streamStageMessage,
  slidesGenerated,
  isReconnecting,
}: StreamProgressLabelInput): string | null {
  if (isReconnecting) return "Reconnecting to server…";
  if (!isStreaming) return null;

  // Prefer the count of slides being generated; fall back to the deck total
  // for streams that don't report it (every non-e& deck, where they're equal).
  const total =
    streamGeneratedSlides && streamGeneratedSlides > 0
      ? streamGeneratedSlides
      : streamTotalSlides;

  if (total && total > 0) {
    if (slidesGenerated === 0) {
      return streamStageMessage || `Preparing ${total} slides`;
    }
    if (slidesGenerated < total) {
      return `Generating slide ${slidesGenerated + 1} of ${total}`;
    }
    return "Finishing up";
  }

  return streamStageMessage || "Generating presentation";
}
