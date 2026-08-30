"use client";

import { cn } from "@/lib/utils";

interface PresentonSplashLoaderProps {
  message?: string;
  className?: string;
}

export const PRESENTON_SPLASH_MIN_DURATION_MS = 3000;

export function PresentonSplashLoader({
  message = "Loading...",
  className,
}: PresentonSplashLoaderProps) {
  return (
    <main
      aria-busy="true"
      aria-label={message}
      className={cn(
        "fixed inset-0 z-[2147483000] flex min-h-screen items-center justify-center overflow-hidden bg-white",
        className
      )}
      role="status"
    >
      <div className="flex flex-col items-center text-center">
        <img src="/eand-logo.png" alt="e&" className="mb-8 h-16 w-auto" />
        <span className="h-9 w-9 animate-spin rounded-full border-4 border-[#f6caca] border-t-[#e60000]" />
        <p className="mt-5 font-inter text-sm font-semibold text-[#e60000]">
          {message}
        </p>
      </div>
    </main>
  );
}
