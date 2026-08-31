"use client";

import React from "react";
import {
  FileText,
  HelpCircle,
  LayoutDashboard,
  Library,
  Settings,
  UsersRound,
} from "lucide-react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Image from "next/image";

export const defaultNavItems = [
  { key: "dashboard" as const, label: "Dashboard", icon: LayoutDashboard },
  { key: "templates" as const, label: "Templates", icon: FileText },
  { key: "community" as const, label: "Community", icon: UsersRound },
];

export const BelongingNavItems = [
  { key: "settings" as const, label: "Settings", icon: Settings },
];

const navigation = [
  { label: "Home", href: "/", icon: LayoutDashboard },
  { label: "Templates", href: "/templates", icon: FileText },
  { label: "Community", href: "/community", icon: UsersRound },
  { label: "Library", href: "/templates", icon: Library },
];

interface DashboardSidebarProps {
  onHomeToggle?: () => void;
  isWorkspaceCollapsed?: boolean;
}

const DashboardSidebar = ({
  onHomeToggle,
  isWorkspaceCollapsed = false,
}: DashboardSidebarProps) => {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 flex h-screen w-[88px] shrink-0 flex-col border-r border-[#e1e3e8] bg-[#f6f6f8]/84 px-2 py-5 backdrop-blur-sm" aria-label="Primary navigation">
      <Link href="/" aria-label="e& Etisalat home" className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#172a5c] p-2 shadow-[0_4px_12px_rgba(23,42,92,0.2)]">
        <Image src="/eand-logo.png" alt="e&" width={56} height={56} className="h-full w-full object-contain" />
      </Link>

      <nav className="mt-7 space-y-3" aria-label="Main navigation">
        {navigation.map(({ label, href, icon: Icon }) => {
          const active = pathname === href || (label === "Library" && pathname.startsWith("/library"));
          const className = `group flex w-full min-h-[58px] flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-medium transition-colors ${active ? "bg-[#fff0f0] text-[#d60000]" : "text-[#586174] hover:bg-[#ececf0] hover:text-[#d60000]"}`;
          if (label === "Home" && onHomeToggle) {
            return <button key={label} type="button" onClick={onHomeToggle} aria-label={isWorkspaceCollapsed ? "Expand workspace menu" : "Collapse workspace menu"} aria-expanded={!isWorkspaceCollapsed} title={isWorkspaceCollapsed ? "Expand workspace menu" : "Collapse workspace menu"} className={`${className} active:scale-95`}><Icon className="h-[19px] w-[19px]" strokeWidth={active ? 2.4 : 1.9} /><span>{label}</span></button>;
          }
          if (href === "/templates") {
            return <button key={label} type="button" aria-label={label} title={label} onClick={() => undefined} className={`${className} active:scale-95`}><Icon className="h-[19px] w-[19px]" strokeWidth={active ? 2.4 : 1.9} /><span>{label}</span></button>;
          }
          return (
            <Link key={label} prefetch={false} href={href} aria-label={label} title={label} className={className}>
              <Icon className="h-[19px] w-[19px]" strokeWidth={active ? 2.4 : 1.9} />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 border-t border-[#e0e2e6] pt-4">
        <Link href="/settings" aria-label="Settings" title="Settings" className={`flex min-h-[58px] flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-medium transition-colors ${pathname === "/settings" ? "bg-[#fff0f0] text-[#d60000]" : "text-[#586174] hover:bg-[#ececf0] hover:text-[#d60000]"}`}><Settings className="h-[19px] w-[19px]" strokeWidth={1.9} /><span>Settings</span></Link>
        <Link href="https://github.com/BasselMahrousseh/AI-Presentation-Studio/tree/restructured-v3" target="_blank" rel="noreferrer" aria-label="Help" title="Help" className="flex min-h-[58px] flex-col items-center justify-center gap-1 rounded-xl text-[11px] font-medium text-[#586174] transition-colors hover:bg-[#ececf0] hover:text-[#d60000]"><HelpCircle className="h-[19px] w-[19px]" strokeWidth={1.9} /><span>Help</span></Link>
      </div>
    </aside>
  );
};

export default DashboardSidebar;
