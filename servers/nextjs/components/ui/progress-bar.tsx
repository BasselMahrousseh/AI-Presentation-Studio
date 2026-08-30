'use client'
import React, { useEffect, useState, useRef } from 'react';

interface ProgressBarProps {
    duration: number;
    onComplete?: () => void;
    /** Skip the fake elapsed-time percentage and show an honest "still working" sweep instead. */
    indeterminate?: boolean;
}

export const ProgressBar = ({ duration, onComplete, indeterminate = false }: ProgressBarProps) => {
    const [progress, setProgress] = useState(0);
    const progressInterval = useRef<NodeJS.Timeout | null>(null);
    const startTime = useRef<number>(Date.now());

    useEffect(() => {
        if (indeterminate) return;

        const updateProgress = () => {
            const currentTime = Date.now();
            const elapsedTime = currentTime - startTime.current;
            const calculatedProgress = (elapsedTime / (duration * 1000)) * 100;

            if (calculatedProgress >= 95) {
                setProgress(95);
                if (progressInterval.current) {
                    clearInterval(progressInterval.current);
                }
                onComplete?.();
                return;
            }

            // Slow down progress after 90%
            if (calculatedProgress > 90) {
                const remainingProgress = Math.min(99 - progress, 0.1);
                setProgress(prev => prev + remainingProgress);
            } else {
                setProgress(Math.min(calculatedProgress, 90));
            }
        };

        progressInterval.current = setInterval(updateProgress, 50);

        return () => {
            if (progressInterval.current) {
                clearInterval(progressInterval.current);
            }
        };
    }, [duration, onComplete, indeterminate]);

    if (indeterminate) {
        return (
            <div className="w-full space-y-2">
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#f4d6d6]">
                    <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-[#b80000] via-[#e60000] to-[#ff4d4d] animate-indeterminate-sweep" />
                </div>
                <style jsx>{`
                    @keyframes indeterminate-sweep {
                        0% {
                            transform: translateX(-100%);
                        }
                        100% {
                            transform: translateX(300%);
                        }
                    }
                    .animate-indeterminate-sweep {
                        animation: indeterminate-sweep 1.2s ease-in-out infinite;
                    }
                `}</style>
            </div>
        );
    }

    return (
        <div className="w-full space-y-2">
            <div className="flex justify-end items-center  text-sm">
                {/* <span>Processing...</span> */}
                <span className='font-inter text-[#191919]/80 text-end font-medium text-xs'>{Math.round(progress)}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-[#f4d6d6]">
              <div
                    className="h-full rounded-full bg-gradient-to-r from-[#b80000] via-[#e60000] to-[#ff4d4d] animate-gradient transition-all duration-300 ease-out"
                    style={{
                        width: `${progress}%`,
                        backgroundSize: '200% 100%',
                    }}
                />
            </div>
            <style jsx>{`
                @keyframes gradient {
                    0% {
                        background-position: 0% 50%;
                    }
                    50% {
                        background-position: 100% 50%;
                    }
                    100% {
                        background-position: 0% 50%;
                    }
                }
                .animate-gradient {
                    animation: gradient 2s linear infinite;
                }
            `}</style>
        </div>
    );
};
