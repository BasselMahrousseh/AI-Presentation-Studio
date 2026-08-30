import React from "react";
import { Loader2 } from "lucide-react";
import Header from "@/app/(presentation-generator)/(dashboard)/dashboard/components/Header";

interface LoadingSpinnerProps {
  message: string;
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ message }) => {
  return (
    <div className="min-h-screen bg-white">
      <Header />
      <div className="flex items-center justify-center aspect-video mx-auto px-6">
        <div className="my-6 space-y-2 rounded-2xl border border-[#e60000]/20 bg-white p-6 text-center shadow-md">
          <img src="/eand-logo.png" alt="e&" className="mx-auto mb-4 h-10 w-auto" />
          <Loader2 className="mx-auto h-6 w-6 animate-spin text-[#e60000]" />
          <p className="font-medium text-[#191919]">{message}</p>
        </div>
      </div>
    </div>
  );
}; 
