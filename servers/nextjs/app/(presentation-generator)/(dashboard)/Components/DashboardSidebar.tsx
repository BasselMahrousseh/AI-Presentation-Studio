"use client";

import React from "react";
import { LayoutDashboard, Star, Brain, Settings, HelpCircle } from "lucide-react";
import { usePathname } from "next/navigation";
import Link from "next/link";



export const defaultNavItems = [
    { key: "dashboard" as const, label: "Dashboard", icon: LayoutDashboard },
    { key: "templates" as const, label: "Standard", icon: Star },
    { key: "designs" as const, label: "Smart", icon: Brain },



];
export const BelongingNavItems = [
    { key: "settings" as const, label: "Settings", icon: Settings },
]

const DashboardSidebar = () => {
    const pathname = usePathname();

    return (
        <aside
            className="sticky top-0 flex h-screen w-[114px] shrink-0 flex-col justify-between border-r border-black/10 bg-[#fafafa] px-4 py-8 backdrop-blur dark:border-white/10 dark:bg-[#0b0b0b]"
            aria-label="Dashboard sidebar"
        >
            <div>

                <Link href={`/dashboard`} className="flex items-center pb-6 border-b border-black/10 gap-2 dark:border-white/10">
                    <div className="cursor-pointer p-1 flex justify-center items-center mx-auto">
                        <img src="/presentation-studio-logo.png" alt="e& logo" className="h-[38px] object-contain w-full" />
                    </div>
                </Link>
                <nav className="pt-6 font-syne" aria-label="Dashboard sections">
                    <div className="  space-y-6">

                        {/* Dashboard */}
                        <Link
                            prefetch={false}
                            href={`/dashboard`}
                            className={[
                                "flex flex-col tex-center items-center gap-2  transition-colors",
                                pathname === "/dashboard" ? "" : "ring-transparent",
                            ].join(" ")}
                            aria-label="Dashboard"
                            title="Dashboard"
                        >
                            <LayoutDashboard className={["h-4 w-4", pathname === "/dashboard" ? "text-[#e60000]" : "text-slate-600 dark:text-zinc-400"].join(" ")} />
                            <span className="text-[11px] text-slate-800 dark:text-zinc-200">Dashboard</span>
                        </Link>
                        <Link
                            prefetch={false}
                            href={`/templates`}
                            className={[
                                "flex flex-col tex-center items-center gap-2  transition-colors",
                                pathname === "/templates" ? "" : "ring-transparent",
                            ].join(" ")}
                            aria-label="Templates"
                            title="Templates"
                        >
                            <div className="flex flex-col cursor-pointer tex-center items-center gap-2  transition-colors">
                                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={`${pathname === "/templates" ? "#e60000" : "#475569"}`} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><path d="M4 14h6" /><path d="M4 2h10" /><rect x="4" y="18" width="16" height="4" rx="1" /><rect x="4" y="6" width="16" height="4" rx="1" /></svg>
                                <span className="text-[11px] text-slate-800 dark:text-zinc-200">Templates</span>
                            </div>
                        </Link>
                        {/* <Link
                            prefetch={false}
                            href={`/theme`}
                            className={[
                                "flex flex-col tex-center items-center gap-2  transition-colors",
                                pathname === "/theme" ? "" : "ring-transparent",
                            ].join(" ")}
                            aria-label="Theme"
                            title="Theme"
                        >
                            <div className="flex flex-col cursor-pointer tex-center items-center gap-2  transition-colors">
                                <Palette className={`h-4 w-4 ${pathname === "/theme" ? "text-[#5146E5]" : "text-slate-600"}`} />
                                <span className="text-[11px] text-slate-800">Themes</span>
                            </div>
                        </Link> */}
                    </div>
                </nav>
            </div>

            <div className="border-t border-black/10 pt-5 font-syne dark:border-white/10">
                <Link
                    href="https://docs.presenton.ai/help"
                    target="_blank"
                    className="flex flex-col items-center gap-2 transition-colors"
                >
                    <HelpCircle className="h-4 w-4" />
                    <span className="text-[11px] text-slate-800 dark:text-zinc-200">Help</span>
                </Link>
            </div>

        </aside>
    );
};

export default DashboardSidebar;
