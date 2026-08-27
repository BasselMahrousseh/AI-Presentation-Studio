import React from "react";
import Image from "next/image";
import { PresentationCard } from "./PresentationCard";
import { PresentationResponse } from "@/app/(presentation-generator)/services/api/dashboard";
import { EmptyState } from "./EmptyState";

interface PresentationGridProps {
  presentations: PresentationResponse[];
  viewMode?: "grid" | "list";
  isLoading?: boolean;
  error?: string | null;
  onPresentationDeleted?: (presentationId: string) => void;
  onPresentationDuplicated?: (presentation: PresentationResponse) => void;
}

export const PresentationGrid = ({
  presentations,
  viewMode = "grid",
  isLoading = false,
  error = null,
  onPresentationDeleted,
  onPresentationDuplicated,
}: PresentationGridProps) => {
  const ShimmerCard = () => (
    <div className="animate-pulse overflow-hidden rounded-lg border border-[#e2e3e8] bg-white shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="relative aspect-[1.72/1] overflow-hidden p-4">
        <Image
          src="/card_bg.svg"
          alt=""
          fill
          sizes="(max-width: 640px) 100vw, (max-width: 1536px) 33vw, 20vw"
          className="absolute inset-0 h-full w-full object-cover opacity-40"
        />
        <div className="relative h-full w-full rounded bg-[#e7e3eb]" />
      </div>
      <div className="relative z-10 border-t border-[#ececf0] bg-white px-4 py-4">
        <div className="flex items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="h-3.5 w-24 rounded bg-gray-200" />
            <div className="h-3 w-16 rounded bg-gray-200" />
          </div>
          <div className="h-5 w-1 rounded-full bg-gray-200" />
        </div>
      </div>
    </div>
  );

  if (isLoading) {
    return (
      <div className="grid w-full grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {[...Array(8)].map((_, i) => (
          <ShimmerCard key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[220px] items-center justify-center rounded-xl border border-[#e2e3e8] bg-[#fcfbfd]">
        <div className="text-center text-[#616a7d]">
          <p className="mb-2">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="font-semibold text-[#5d198f] underline hover:text-[#3e0f65]"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (!presentations || presentations.length === 0) {
    return <EmptyState />;
  }

  return (
    <div
      className={
        viewMode === "grid"
          ? "grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
          : "grid grid-cols-1 gap-4"
      }
    >
      {presentations.map((presentation) => (

        <PresentationCard
          key={presentation.id}
          id={presentation.id}
          title={presentation.title}
          presentation={presentation}
          viewMode={viewMode}
          onDeleted={onPresentationDeleted}
          onDuplicated={onPresentationDuplicated}
        />
      ))}
    </div>
  );
};
