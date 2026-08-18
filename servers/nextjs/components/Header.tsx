"use client";

import React from "react";
import Link from "next/link";
import { BrandThemeToggle } from "./BrandThemeToggle";

const Header: React.FC = () => {
  return (
    <header className="w-full border-b border-black/10 bg-white/85 backdrop-blur supports-[backdrop-filter]:bg-white/85 sticky top-0 z-50 dark:border-white/10 dark:bg-[#0b0b0b]/90">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link href="/" className="flex items-center gap-3">
            <img src="/presentation-studio-logo.png" alt="e& logo" className="h-8 w-auto" />
            <span className="text-sm font-bold tracking-tight text-[#111111] dark:text-white">Presentation Studio</span>
          </Link>

          <BrandThemeToggle />

        </div>
      </div>
    </header>
  );
};

export default Header;
