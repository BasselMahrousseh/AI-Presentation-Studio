import { cn } from "@/lib/utils";
import { ProgressBar } from "./progress-bar";
import { useEffect, useState } from "react";

interface OverlayLoaderProps {
  text?: string;
  className?: string;
  show: boolean;
  showProgress?: boolean;
  duration?: number;
  /** Show an honest "still working" sweep instead of a fabricated elapsed-time percentage. */
  indeterminateProgress?: boolean;
  extra_info?: string;
  onProgressComplete?: () => void;
}

export const OverlayLoader = ({
  text,
  className,
  show,
  showProgress = false,
  duration = 10,
  indeterminateProgress = false,
  onProgressComplete,
  extra_info,
}: OverlayLoaderProps) => {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (show) {
      setIsVisible(true);
    } else {
      setIsVisible(false);
    }
  }, [show]);

  if (!show) return null;

  return (
    <div
      style={{
        zIndex: 1000,
      }}
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center bg-black/75 transition-opacity duration-300",
        isVisible ? "opacity-100" : "opacity-0"
      )}
    >
      <div
        className={cn(
          "relative flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-[#e60000]/20 bg-white px-6 pb-10 pt-8 shadow-2xl",
          "min-w-[280px] sm:min-w-[447px] transition-all duration-400 ease-out",
          isVisible ? "opacity-100 scale-100" : "opacity-0 scale-90",
          className
        )}
      >
        <img src="/eand-logo.png" alt="e&" className="mb-7 h-12 w-auto object-contain" />
        <div className="overlay-loader-dots shrink-0" role="status" aria-label="Loading" />
        {showProgress ? (
          <div className="w-full space-y-6 pt-4">
            <ProgressBar
              duration={duration}
              onComplete={onProgressComplete}
              indeterminate={indeterminateProgress}
            />
            {text && (
              <div className="space-y-1">
                <p className="text-[#191919] text-base text-center font-semibold font-inter">
                  {text}
                </p>
                {extra_info && (
                  <p className="text-[#191919]/70 text-xs text-center font-medium font-inter">
                    {extra_info}
                  </p>
                )}
              </div>
            )}
          </div>
        ) : (
          <>
            <p className="text-[#191919] text-base text-center font-semibold font-inter">
              {text}
            </p>
            {extra_info && (
              <p className="text-[#191919]/70 text-xs text-center font-medium font-inter">
                {extra_info}
              </p>
            )}
          </>
        )}
      </div>

      <style jsx>{`
        .overlay-loader-dots {
          width: 50px;
          aspect-ratio: 1;
          --_c: no-repeat radial-gradient(farthest-side, #e60000 92%, #0000);
          background: var(--_c) top, var(--_c) left, var(--_c) right,
            var(--_c) bottom;
          background-size: 12px 12px;
          animation: overlay-loader-l7 1s infinite;
        }
        @keyframes overlay-loader-l7 {
          to {
            transform: rotate(0.5turn);
          }
        }
      `}</style>
    </div>
  );
};
