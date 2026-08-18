"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

const DARK_ROUTE_PREFIXES = ["/custom-template", "/presentation"];

export default function RouteTheme() {
  const pathname = usePathname();

  useEffect(() => {
    const isDarkRoute = DARK_ROUTE_PREFIXES.some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    );
    document.documentElement.classList.toggle("dark", isDarkRoute);

    return () => document.documentElement.classList.remove("dark");
  }, [pathname]);

  return null;
}
