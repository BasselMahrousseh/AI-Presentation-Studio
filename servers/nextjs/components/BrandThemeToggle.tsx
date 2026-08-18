"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

export function BrandThemeToggle() {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggleTheme() {
    const nextIsDark = !isDark;
    document.documentElement.classList.toggle("dark", nextIsDark);
    setIsDark(nextIsDark);
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-black/10 bg-white text-[#111111] transition hover:border-[#e60000] hover:text-[#e60000] dark:border-white/15 dark:bg-[#151515] dark:text-white"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
