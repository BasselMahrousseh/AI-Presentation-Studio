"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Bell, ChevronDown, Clock3, FileText, FolderPlus, Grid2X2, Heart,
  LayoutGrid, Library, List, Plus, Search, Share2, Sparkles, Trash2, UserRound,
} from "lucide-react";
import { DashboardApi, type PresentationResponse } from "@/app/(presentation-generator)/services/api/dashboard";
import { PresentationGrid } from "@/app/(presentation-generator)/(dashboard)/dashboard/components/PresentationGrid";
import { LegacyPresentationsTable } from "@/app/(presentation-generator)/(dashboard)/dashboard/components/LegacyPresentationsTable";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { usePathname } from "next/navigation";

type LibraryTab = "all" | "recent" | "created" | "favorites";

const sortPresentationsNewestFirst = (presentations: PresentationResponse[]) =>
  [...presentations].sort((a, b) => {
    const createdAtA = Date.parse(a.created_at);
    const createdAtB = Date.parse(b.created_at);
    return (Number.isNaN(createdAtB) ? 0 : createdAtB) - (Number.isNaN(createdAtA) ? 0 : createdAtA);
  });

const libraryNavItems = [
  { label: "Presentations", icon: FileText, active: true },
  { label: "Search", icon: Search },
  { label: "Shared with you", icon: Share2 },
  { label: "Templates", icon: LayoutGrid, href: "/templates" },
  { label: "Brand library", icon: Library },
];

function WorkspaceSidebar({ onSearch }: { onSearch: () => void }) {
  return (
    <aside className="hidden h-screen w-[300px] shrink-0 border-r border-[#e7e8ec] bg-[#fbfbfc]/85 px-4 py-6 backdrop-blur-sm xl:flex xl:flex-col" aria-label="Workspace navigation">
      <button type="button" className="flex w-full items-center gap-3 rounded-xl px-2 py-1 text-left transition-colors hover:bg-[#f1f2f4]">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#172a5c] text-sm font-semibold text-white shadow-sm">e&amp;</span>
        <span className="min-w-0 flex-1"><span className="block truncate text-[15px] font-semibold text-[#17213c]">e&amp; Presentation Studio</span><span className="block text-xs text-[#7a8090]">Enterprise</span></span>
        <ChevronDown className="h-4 w-4 text-[#616a7d]" />
      </button>

      <Link href="/generate" className="mt-6 flex h-10 items-center justify-center gap-2 rounded-full border border-[#ffd1d1] bg-white px-4 text-sm font-semibold text-[#e60000] shadow-sm transition-colors hover:border-[#f27c7c] hover:bg-[#fff8f8]"><Sparkles className="h-4 w-4" />Create with AI</Link>

      <nav className="mt-4 space-y-1" aria-label="Presentation library">
        {libraryNavItems.map(({ label, icon: Icon, active, href }) => {
          const className = `flex h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors ${active ? "bg-[#fff0f0] font-semibold text-[#d60000]" : "font-medium text-[#31394c] hover:bg-[#f0f1f4]"}`;
          const content = <><Icon className="h-[18px] w-[18px]" strokeWidth={active ? 2.3 : 1.9} /><span>{label}</span>{label === "Search" && <span className="ml-auto text-xs text-[#8b90a0]">Ctrl K</span>}</>;
          return href === "/templates" ? <button key={label} type="button" className={`${className} w-full text-left active:scale-[0.99]`} onClick={() => undefined}>{content}</button> : href ? <Link key={label} href={href} className={className}>{content}</Link> : <button key={label} type="button" className={`${className} w-full text-left`} onClick={label === "Search" ? onSearch : undefined}>{content}</button>;
        })}
      </nav>

      <div className="mt-8"><p className="px-3 text-[11px] font-bold uppercase tracking-[0.12em] text-[#7a8090]">Folders</p><div className="mt-3 rounded-xl bg-[#f0f0f3] px-5 py-6 text-center"><FolderPlus className="mx-auto h-5 w-5 text-[#e60000]" /><p className="mt-3 text-sm leading-5 text-[#586073]">Keep projects organised and share them with your team.</p><button type="button" className="mt-3 text-sm font-semibold text-[#d60000] transition-colors hover:text-[#ad0000]">Create a folder</button></div></div>
      <button type="button" className="mt-auto flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium text-[#51596b] transition-colors hover:bg-[#f0f1f4]"><Trash2 className="h-[17px] w-[17px]" /> Trash</button>
    </aside>
  );
}

function LibraryTabButton({ active, icon: Icon, children, onClick }: { active: boolean; icon: React.ComponentType<{ className?: string; strokeWidth?: number }>; children: React.ReactNode; onClick: () => void }) {
  return <button type="button" onClick={onClick} className={`inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors ${active ? "bg-[#fff0f0] text-[#d60000]" : "text-[#2b3448] hover:bg-[#f3f3f5]"}`}><Icon className="h-[18px] w-[18px]" strokeWidth={2} />{children}</button>;
}

const DashboardPage: React.FC<{ workspaceSidebarCollapsed?: boolean }> = ({
  workspaceSidebarCollapsed = false,
}) => {
  const pathname = usePathname();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [presentations, setPresentations] = useState<PresentationResponse[]>([]);
  const [legacyPresentations, setLegacyPresentations] = useState<PresentationResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deckViewMode, setDeckViewMode] = useState<"grid" | "list">("grid");
  const [activeTab, setActiveTab] = useState<LibraryTab>("recent");
  const [searchQuery, setSearchQuery] = useState("");

  const sortedPresentations = useMemo(() => sortPresentationsNewestFirst(presentations), [presentations]);
  const sortedLegacyPresentations = useMemo(() => sortPresentationsNewestFirst(legacyPresentations), [legacyPresentations]);
  const visiblePresentations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const favorites = sortedPresentations.filter((presentation) => {
      const item = presentation as PresentationResponse & { is_favorite?: boolean; favorite?: boolean };
      return item.is_favorite || item.favorite;
    });
    const tabPresentations = activeTab === "favorites" ? favorites : sortedPresentations;
    return query ? tabPresentations.filter((presentation) => presentation.title?.toLowerCase().includes(query)) : tabPresentations;
  }, [activeTab, searchQuery, sortedPresentations]);

  const fetchPresentations = useCallback(async () => {
    let fetchedCount = 0;
    let hasError = false;
    try {
      setIsLoading(true); setError(null);
      const [supported, legacy] = await Promise.all([DashboardApi.getPresentations("v2-standard"), DashboardApi.getPresentations("v1-standard", { includeSlides: false })]);
      fetchedCount = supported.length + legacy.length;
      setPresentations(supported); setLegacyPresentations(legacy);
    } catch {
      hasError = true;
      setError("We couldn’t load your presentations. Please refresh and try again.");
      setPresentations([]); setLegacyPresentations([]);
    } finally {
      trackEvent(MixpanelEvent.Dashboard_Page_Viewed, { pathname, presentation_count: fetchedCount, load_failed: hasError });
      setIsLoading(false);
    }
  }, [pathname]);

  useEffect(() => { void fetchPresentations(); }, [fetchPresentations]);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); searchInputRef.current?.focus(); }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const removePresentation = (presentationId: string) => setPresentations((current) => current.filter((presentation) => presentation.id !== presentationId));
  const removeLegacyPresentations = (presentationIds: string[]) => { const deletedIds = new Set(presentationIds); setLegacyPresentations((current) => current.filter((presentation) => !deletedIds.has(presentation.id))); };

  return (
    <div className="relative flex min-h-screen w-full bg-white/55 font-sans text-[#17213c] backdrop-blur-[1px]">
      {!workspaceSidebarCollapsed && <WorkspaceSidebar onSearch={() => searchInputRef.current?.focus()} />}
      <main className="min-w-0 flex-1 px-5 py-6 sm:px-8 lg:px-10">
        <header className="flex min-h-10 items-center justify-between gap-4"><div className="flex items-center gap-3"><FileText className="h-5 w-5 text-[#e60000]" strokeWidth={2.3} /><h1 className="text-xl font-bold tracking-[-0.02em] text-[#17213c]">Presentations</h1></div><div className="flex items-center gap-5"><span className="hidden items-center gap-2 text-sm font-semibold text-[#d60000] sm:flex"><Sparkles className="h-4 w-4" /> e&amp; credits</span><button type="button" aria-label="Notifications" className="rounded-lg p-2 text-[#253452] transition-colors hover:bg-[#f2f0f5]"><Bell className="h-5 w-5" /></button></div></header>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link href="/generate" onClick={() => trackEvent(MixpanelEvent.Dashboard_New_Presentation_Clicked, { pathname, source: "etisalat_dashboard_create" })} className="inline-flex h-11 items-center gap-2 rounded-full bg-[#e60000] px-5 text-sm font-semibold text-white shadow-[0_6px_18px_rgba(230,0,0,0.2)] transition-all hover:bg-[#b80000] hover:shadow-[0_8px_22px_rgba(230,0,0,0.3)]"><Plus className="h-5 w-5" /> Create presentation <span className="rounded-md bg-white/20 px-1.5 py-0.5 text-[11px]">AI</span></Link>
          <label className="relative ml-auto hidden w-full max-w-[260px] sm:block"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#727a8c]" /><input ref={searchInputRef} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search presentations" className="h-10 w-full rounded-full border border-[#e0dde5] bg-[#fcfcfd] pl-10 pr-4 text-sm outline-none transition focus:border-[#e60000] focus:ring-4 focus:ring-[#ffeded]" /></label>
        </div>

        <div className="mt-11 flex flex-wrap items-center justify-between gap-3 border-b border-[#ececf0] pb-5"><div className="flex flex-wrap items-center gap-1"><LibraryTabButton active={activeTab === "all"} icon={FileText} onClick={() => setActiveTab("all")}>All</LibraryTabButton><LibraryTabButton active={activeTab === "recent"} icon={Clock3} onClick={() => setActiveTab("recent")}>Recently created</LibraryTabButton><LibraryTabButton active={activeTab === "created"} icon={UserRound} onClick={() => setActiveTab("created")}>Created by you</LibraryTabButton><LibraryTabButton active={activeTab === "favorites"} icon={Heart} onClick={() => setActiveTab("favorites")}>Favorites</LibraryTabButton></div><div className="flex items-center rounded-full bg-[#ededf0] p-1" aria-label="Presentation layout"><button type="button" onClick={() => setDeckViewMode("grid")} aria-label="Grid view" aria-pressed={deckViewMode === "grid"} className={`flex h-8 items-center gap-1.5 rounded-full px-3 text-sm font-semibold ${deckViewMode === "grid" ? "bg-white text-[#d60000] shadow-sm" : "text-[#5d6471]"}`}><Grid2X2 className="h-4 w-4" /> Grid</button><button type="button" onClick={() => setDeckViewMode("list")} aria-label="List view" aria-pressed={deckViewMode === "list"} className={`flex h-8 items-center gap-1.5 rounded-full px-3 text-sm font-semibold ${deckViewMode === "list" ? "bg-white text-[#d60000] shadow-sm" : "text-[#5d6471]"}`}><List className="h-4 w-4" /> List</button></div></div>

        <div className="mt-6"><PresentationGrid presentations={visiblePresentations} viewMode={deckViewMode} isLoading={isLoading} error={error} onPresentationDeleted={removePresentation} onPresentationDuplicated={(presentation) => setPresentations((current) => [presentation, ...current])} /></div>
        {!isLoading && sortedLegacyPresentations.length > 0 && <div className="mt-12"><LegacyPresentationsTable presentations={sortedLegacyPresentations} onPresentationsDeleted={removeLegacyPresentations} /></div>}
      </main>
    </div>
  );
};

export default DashboardPage;
