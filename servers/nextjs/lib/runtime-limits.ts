export class BoundedTextBuffer {
  private text = "";
  private truncatedChars = 0;

  constructor(private readonly limit = 8192) {}

  append(value: Buffer | string): void {
    const next = Buffer.isBuffer(value) ? value.toString("utf8") : value;
    let combined = this.text + next;
    if (combined.length > this.limit) {
      const overflow = combined.length - this.limit;
      this.truncatedChars += overflow;
      combined = combined.slice(overflow);
    }
    this.text = combined;
  }

  toString(): string {
    const body = this.text.trim();
    if (!this.truncatedChars) return body;
    return `... [truncated ${this.truncatedChars} chars]\n${body}`.trim();
  }
}

export function memorySnapshotMb(): Record<string, number> {
  const usage = process.memoryUsage();
  return {
    rss_mb: Math.round(usage.rss / 1024 / 1024),
    heap_used_mb: Math.round(usage.heapUsed / 1024 / 1024),
    heap_total_mb: Math.round(usage.heapTotal / 1024 / 1024),
    external_mb: Math.round(usage.external / 1024 / 1024),
    array_buffers_mb: Math.round(usage.arrayBuffers / 1024 / 1024),
  };
}

/**
 * A simple promise-based counting semaphore. Node has no built-in
 * equivalent to Python's `threading.Semaphore`. Module-level state in a
 * Next.js route handler persists across requests within one server process
 * (it does not survive a restart, and does not coordinate across multiple
 * server processes/instances) - that's what makes an in-process cap like
 * this meaningful for e.g. limiting how many child processes one server can
 * have spawned at once.
 */
export class AsyncSemaphore {
  private available: number;
  private readonly waiters: Array<() => void> = [];

  constructor(private readonly max: number) {
    this.available = max;
  }

  /** Resolves once a slot is held. Always pair with `release()`, in a `finally`. */
  async acquire(): Promise<void> {
    if (this.available > 0) {
      this.available -= 1;
      return;
    }
    await new Promise<void>((resolve) => {
      this.waiters.push(resolve);
    });
  }

  /** Hands the freed slot directly to the longest-waiting caller, if any. */
  release(): void {
    const next = this.waiters.shift();
    if (next) {
      next();
      return;
    }
    this.available = Math.min(this.max, this.available + 1);
  }
}
