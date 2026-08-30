"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

interface OutlineStandardHeaderProps {
  title: string;
  onBack: () => void;
  slideCount?: number;
}

const OutlineStandardHeader = ({
  title,
  onBack,
  slideCount,
}: OutlineStandardHeaderProps) => (
  <header className="sticky top-0 z-[60] h-[66px] w-full border-b border-[#ece9e9] bg-white font-syne shadow-[0_1px_10px_rgba(6,22,46,0.04)]">
    <div className="flex h-full items-center justify-between px-5 sm:px-6">
      <div className="flex min-w-0 items-center gap-4">
        <Link
          href="/"
          aria-label="Go to e& Presentation Studio"
          className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E30613]/30"
        >
          <Image
            src="/eand-logo.png"
            alt="e&"
            width={62}
            height={32}
            className="h-8 w-[62px] object-contain object-left"
          />
        </Link>
        <span className="hidden h-6 w-px bg-[#e3e3e5] sm:block" />
        <h1 className="truncate text-sm font-semibold tracking-[-0.01em] text-[#172a5c] sm:text-[15px]">
          {title}
        </h1>
      </div>

      <nav
        className="absolute left-1/2 hidden -translate-x-1/2 items-center rounded-full border border-[#e8e9ed] bg-[#f7f8fa] p-1 md:flex"
        aria-label="Workspace navigation"
      >
        <Link
          href="/"
          className="rounded-full px-3 py-1.5 text-xs font-medium text-[#667085] transition hover:text-[#172a5c]"
        >
          Dashboard
        </Link>
        <span
          aria-current="page"
          className="rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-[#e60000] shadow-[0_1px_4px_rgba(23,42,92,0.10)]"
        >
          Outline
        </span>
      </nav>

      <div className="ml-auto flex shrink-0 items-center gap-3">
        {typeof slideCount === "number" && (
          <span className="hidden rounded-full bg-[#fff1f1] px-3 py-1.5 text-xs font-semibold text-[#c90000] sm:inline-flex">
            {slideCount} {slideCount === 1 ? "slide" : "slides"}
          </span>
        )}
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2 rounded-full border border-[#e6e7eb] px-3 py-2 text-xs font-semibold text-[#172a5c] transition-colors hover:border-[#f0b6b6] hover:bg-[#fff5f5] hover:text-[#e60000] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E30613]/30"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back
        </button>
      </div>
    </div>
  </header>
);

export default OutlineStandardHeader;
