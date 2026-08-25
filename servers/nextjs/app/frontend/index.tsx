'use client';
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Bell,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  Download,
  FileText,
  FolderKanban,
  GalleryHorizontalEnd,
  Grid2X2,
  Layers3,
  LayoutDashboard,
  MoreHorizontal,
  Palette,
  Plus,
  Redo2,
  RotateCcw,
  Search,
  Settings2,
  Sparkles,
  Moon,
  Sun,
  Table2,
  Undo2,
  Users,
  WandSparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { getApiUrl } from "@/utils/api";
import { useTemplateSummaries } from "../(presentation-generator)/hooks/useTemplateSummaries";
import { TemplateThumbnailPreview } from "../(presentation-generator)/components/TemplateListUi";


type View = "dashboard" | "create" | "generating" | "editor";

type Slide = {
  title: string;
  kicker: string;
  archetype: string;
  message: string;
  summary: string;
  kind: "title" | "diagram" | "cards" | "table" | "quote";
};

const slides: Slide[] = [
  { title: "Retrieval-Augmented Generation", kicker: "A practical guide for software teams", archetype: "Title slide", message: "Ground language models in the information that matters.", summary: "An introduction to RAG, why it matters, and what we'll cover.", kind: "title" },
  { title: "Why models need a memory", kicker: "The context gap", archetype: "Problem statement", message: "Your model is powerful. Your data is somewhere else.", summary: "Training data can be stale, generic, or disconnected from private company knowledge.", kind: "cards" },
  { title: "How RAG works", kicker: "The core architecture", archetype: "Architecture", message: "Retrieve relevant context, then generate with confidence.", summary: "A three-step pipeline that connects a user's question to grounded model output.", kind: "diagram" },
  { title: "From question to answer", kicker: "A repeatable workflow", archetype: "Process", message: "Every answer starts with a better search.", summary: "The request is embedded, matched against a vector index, and passed to the LLM with citations.", kind: "diagram" },
  { title: "What makes a good retrieval system?", kicker: "Design principles", archetype: "Framework", message: "Relevance is a product decision, not just a model metric.", summary: "Key considerations for chunking, embeddings, ranking, and evaluation.", kind: "cards" },
  { title: "The trade-offs", kicker: "Advantages & limitations", archetype: "Comparison", message: "More context is not always better context.", summary: "RAG improves freshness and attribution, while adding latency and retrieval complexity.", kind: "table" },
];

const recentDecks = [
  { title: "RAG for Software Engineers", slides: 10, modified: "Just now", status: "Ready", tone: "blue", initials: "RAG" },
  { title: "Q3 Product Strategy", slides: 14, modified: "Yesterday", status: "Ready", tone: "orange", initials: "Q3" },
  { title: "Design system principles", slides: 8, modified: "Mar 18, 2025", status: "Draft", tone: "violet", initials: "DS" },
];

const navItems = [
  { label: "Home", icon: LayoutDashboard },
  { label: "Projects", icon: FolderKanban },
  { label: "Templates", icon: GalleryHorizontalEnd },
  { label: "Assets", icon: Layers3 },
];

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={cn("flex items-center gap-2.5", compact && "gap-2")}><img src="/eand-logo.png" alt="e&" className="h-7 w-auto object-contain" /><span className="font-semibold tracking-[-0.02em] text-slate-900">{compact ? "Studio" : "e& Presentation Studio"}</span></div>;
}

function EandNavbar({ darkMode, onToggleDarkMode }: { darkMode: boolean; onToggleDarkMode: () => void }) {
  return (
    <header className="sticky top-0 z-50 h-[72px] border-b-2 border-[#e60000] bg-white px-5 shadow-sm transition-colors dark:bg-[#171717] dark:shadow-black/20 sm:px-8">
      <div className="mx-auto flex h-full max-w-7xl items-center justify-between">
        <button type="button" onClick={() => window.location.assign("/frontend")} className="flex items-center" aria-label="e& Presentation Studio home">
          <img src="/eand-logo.png" alt="e&" className="h-10 w-auto object-contain" />
        </button>
        <nav className="flex items-center gap-4 text-sm font-semibold text-slate-700 dark:text-zinc-200">
          <a href="#create" className="transition hover:text-[#e60000]">Create</a>
          <a href="/template-preview" className="transition hover:text-[#e60000]">Templates</a>
          <button
            type="button"
            onClick={onToggleDarkMode}
            aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            aria-pressed={darkMode}
            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-[#e60000]/20 bg-[#fff5f5] text-[#e60000] transition hover:bg-[#ffe4e4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#e60000] focus-visible:ring-offset-2 dark:bg-[#351010] dark:text-[#ff7a7a] dark:hover:bg-[#4a1515] dark:focus-visible:ring-offset-[#171717]"
          >
            {darkMode ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </nav>
      </div>
    </header>
  );
}

function Sidebar({ view, setView }: { view: View; setView: (v: View) => void }) {
  return <aside className="hidden w-[232px] shrink-0 flex-col border-r border-slate-200/80 bg-[#fbfcfe] px-3 py-5 lg:flex">
    <div className="mb-8 px-3"><Brand /></div>
    <div className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Workspace</div>
    <nav className="space-y-1">
      {navItems.map(({ label, icon: Icon }) => <button key={label} onClick={() => setView(label === "Home" ? "dashboard" : "dashboard")} className={cn("nav-item", label === "Home" && view === "dashboard" && "active")}><Icon size={17} />{label}</button>)}
    </nav>
    <div className="mt-7 mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Manage</div>
    <button className="nav-item"><Settings2 size={17} />Settings</button>
    <div className="mt-auto rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm">
      <div className="mb-2 flex items-center justify-between"><span className="text-xs font-semibold text-slate-700">Workspace usage</span><span className="text-[11px] text-slate-400">3 / 10</span></div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full w-[30%] rounded-full bg-[#4779e8]" /></div>
      <p className="mt-2 text-[11px] leading-4 text-slate-400">7 presentations remaining this month</p>
      <button className="mt-3 text-xs font-semibold text-[#3567d6]">Upgrade plan <ArrowRight className="ml-1 inline" size={12} /></button>
    </div>
  </aside>;
}

function Topbar({ view, onCreate }: { view: View; onCreate: () => void }) {
  const title = view === "dashboard" ? "Good morning, Joshua" : view === "create" ? "Create a new presentation" : "RAG for Software Engineers";
  return <header className="flex h-[72px] items-center justify-between border-b border-slate-200/80 bg-white px-5 sm:px-8">
    <div className="flex items-center gap-3 lg:hidden"><Brand compact /><span className="text-slate-300">/</span></div>
    <div className="hidden text-[13px] text-slate-400 lg:block">Workspace <span className="mx-2 text-slate-300">/</span><span className="font-medium text-slate-700">{title}</span></div>
    <div className="ml-auto flex items-center gap-2.5"><button className="icon-button hidden sm:flex"><Search size={17} /></button><button className="icon-button relative"><Bell size={17} /><span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-[#4779e8] ring-2 ring-white" /></button><div className="ml-1 flex items-center gap-2 border-l border-slate-200 pl-3"><div className="avatar">JS</div><span className="hidden text-sm font-medium text-slate-700 sm:block">Joshua</span><ChevronDown size={14} className="text-slate-400" /></div>{view === "dashboard" && <Button onClick={onCreate} className="ml-2 hidden h-9 rounded-lg bg-[#3567d6] px-3.5 text-xs shadow-[0_4px_10px_rgba(53,103,214,.18)] hover:bg-[#2d5cc8] sm:flex"><Plus size={15} /> New presentation</Button>}</div>
  </header>;
}

function Dashboard({ onCreate }: { onCreate: () => void }) {
  return <main className="page-shell">
    <section className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><p className="mb-2 text-sm text-slate-400">Tuesday, March 25, 2025</p><h1 className="text-[28px] font-semibold tracking-[-0.04em] text-slate-900 sm:text-[32px]">Your workspace</h1><p className="mt-1.5 text-sm text-slate-500">Create, refine, and share presentations that move ideas forward.</p></div><Button onClick={onCreate} className="h-11 w-fit rounded-lg bg-[#3567d6] px-5 text-sm font-semibold shadow-[0_6px_16px_rgba(53,103,214,.18)] hover:bg-[#2d5cc8]"><Plus size={17} /> Create presentation</Button></section>
    <section className="mb-9 grid gap-4 md:grid-cols-3"><div className="stat-card"><div className="stat-icon blue"><FileText size={17} /></div><div><p className="text-xs text-slate-400">Presentations created</p><p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">24</p></div><span className="ml-auto rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-600">+12%</span></div><div className="stat-card"><div className="stat-icon violet"><Clock3 size={17} /></div><div><p className="text-xs text-slate-400">Time saved</p><p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">18.5h</p></div><span className="ml-auto text-[11px] text-slate-400">this month</span></div><div className="stat-card"><div className="stat-icon orange"><Users size={17} /></div><div><p className="text-xs text-slate-400">Shared with team</p><p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">08</p></div><span className="ml-auto text-[11px] text-slate-400">across 3 teams</span></div></section>
    <section><div className="mb-4 flex items-center justify-between"><h2 className="text-base font-semibold text-slate-900">Recent presentations</h2><button className="text-xs font-semibold text-[#3567d6]">View all <ArrowRight className="ml-1 inline" size={13} /></button></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{recentDecks.map((deck, i) => <DeckCard key={deck.title} deck={deck} index={i} onClick={onCreate} />)}<button onClick={onCreate} className="group flex min-h-[236px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/50 transition hover:border-[#8eabe9] hover:bg-[#f7f9ff]"><div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-500 transition group-hover:bg-[#e9efff] group-hover:text-[#3567d6]"><Plus size={19} /></div><span className="text-sm font-semibold text-slate-700">Start from scratch</span><span className="mt-1 text-xs text-slate-400">Or choose a template</span></button></div></section>
  </main>;
}

function DeckCard({ deck, index, onClick }: { deck: typeof recentDecks[number]; index: number; onClick: () => void }) {
  return <button onClick={onClick} className="deck-card text-left"><div className={cn("deck-thumb", `thumb-${deck.tone}`)}><div className="thumb-top"><span>{deck.initials}</span><span className="opacity-60">{String(index + 1).padStart(2, "0")}</span></div><div className="thumb-lines"><i /><i /><i /></div><div className="thumb-shape" /></div><div className="flex items-start justify-between pt-3"><div><h3 className="text-sm font-semibold text-slate-800">{deck.title}</h3><p className="mt-1 text-xs text-slate-400">{deck.slides} slides <span className="mx-1.5">·</span>{deck.modified}</p></div><MoreHorizontal size={17} className="text-slate-400" /></div><div className="mt-3 flex items-center gap-2"><span className={cn("status-dot", deck.status === "Ready" ? "bg-emerald-500" : "bg-amber-400")} /> <span className="text-[11px] font-medium text-slate-500">{deck.status}</span></div></button>;
}

function CreateView({
  onGenerate,
  onGenerateOutline,
  onBack,
  selectedTemplateId,
  onSelectTemplateId,
}: {
  onGenerate: (
    prompt: string,
    templateId: string,
    useEandTemplate: boolean
  ) => Promise<void>;
  onGenerateOutline: (prompt: string, templateId: string) => Promise<void>;
  onBack: () => void;
  selectedTemplateId: string;
  onSelectTemplateId: (templateId: string) => void;
}) {
  const [prompt, setPrompt] = useState("");

  return (
    <main id="create" className="create-shell flex min-h-screen w-full items-center justify-center bg-white px-5 py-12 text-slate-900 transition-colors dark:bg-[#111111] dark:text-white sm:px-8">
      {/* <button
        onClick={onBack}
        className="mb-8 flex items-center gap-2 text-xs font-semibold text-slate-400 hover:text-slate-700"
      >
        <ChevronLeft size={16} />
        Back to workspace
      </button> */}

      <div className="mx-auto w-full max-w-[800px]">
        <div className="mb-9">
          {/* <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-[#e9efff] text-[#3567d6]">
            <WandSparkles size={19} />
          </div> */}

          <h1 className="text-[30px] font-semibold tracking-[-0.04em] text-slate-900 dark:text-white">
            Create a new presentation
          </h1>

          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            Turn an idea into a compelling deck in minutes.
          </p>
        </div>

        <div className="presentation-studio-prompt rounded-2xl border border-black/10 bg-[#fafafa] p-5 shadow-[0_18px_45px_rgba(0,0,0,0.08)] transition-shadow focus-within:border-[#e60000]/50 focus-within:shadow-[0_18px_45px_rgba(230,0,0,0.13)] dark:border-white/10 dark:bg-[#0d0d0d]">
          <div className="mb-3 flex items-center justify-between">
            <label className="text-sm font-semibold text-slate-800 dark:text-white">
              What do you want to present?
            </label>

            <span className="rounded-full bg-[#fff0f0] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[#d40000] dark:bg-[#3a1010] dark:text-[#ff7777]">
              AI assisted
            </span>
          </div>

          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the presentation you want to create..."
            className="min-h-[180px] resize-none rounded-xl border border-slate-200 bg-white px-4 py-3 text-[15px] leading-7 text-slate-900 shadow-inner shadow-black/[0.02] placeholder:text-slate-400 focus-visible:border-[#e60000] focus-visible:ring-2 focus-visible:ring-[#e60000]/15 dark:border-white/10 dark:bg-[#171717] dark:text-white dark:placeholder:text-zinc-500"
          />

          <div className="mt-4 flex flex-col justify-between gap-3 border-t border-slate-200 pt-4 dark:border-white/10 sm:flex-row sm:items-center">
            <p className="max-w-[500px] text-xs leading-5 text-slate-500 dark:text-zinc-400">
              Try: “Create a 10-slide presentation explaining how
              Retrieval-Augmented Generation works for software engineers.”
            </p>

            {/* <button className="flex w-fit items-center gap-1.5 text-xs font-semibold text-[#e60000] transition-colors hover:text-[#b80000] dark:text-[#ff6262]">
              <Sparkles size={14} />
              Improve prompt
            </button> */}
          </div>
        </div>
        <TemplatePicker
          selectedTemplateId={selectedTemplateId}
          onSelectTemplateId={onSelectTemplateId}
        />

        <div className="mt-8 flex items-center justify-between border-t border-slate-200 pt-5 dark:border-white/10">
          {/* <p className="hidden text-xs text-slate-400 dark:text-zinc-500 sm:block">
            You can edit everything after generation.
          </p> */}

          <div className="flex w-full flex-col gap-2 sm:ml-auto sm:w-auto sm:flex-row">
            <Button
              variant="outline"
              onClick={() => onGenerate(prompt, selectedTemplateId, false)}
              className="h-11 w-full rounded-lg border-[#d0d5dd] bg-white px-5 text-sm font-semibold text-slate-700 hover:bg-slate-50 sm:w-auto"
            >
              <Sparkles size={16} />
              Generate presentation
            </Button>
            <Button
              onClick={() => onGenerate(prompt, selectedTemplateId, true)}
              className="h-11 w-full rounded-lg bg-[#e60000] px-5 text-sm font-semibold shadow-[0_6px_16px_rgba(230,0,0,.2)] hover:bg-[#c40000] sm:w-auto"
            >
              <Sparkles size={16} />
              Generate with e&amp; template
            </Button>

            <Button
              type="button"
              disabled={!prompt.trim()}
              onClick={() => onGenerateOutline(prompt, selectedTemplateId)}
              className="h-11 w-full rounded-lg bg-[#ff848c] px-5 text-sm font-semibold shadow-[0_6px_16px_rgba(230,0,0,.2)] hover:bg-[#c40000] sm:w-auto"
            >
              <Sparkles size={16} />
              Generate Outlines
            </Button>
          </div>
        </div>
      </div>
    </main>
  );
}

function Generating() {
  return (
    <main className="flex flex-1 items-center justify-center bg-[#f8fafc] px-5 py-16">
      <div className="w-full max-w-[530px] text-center">
        <div className="generation-orb">
          <div className="generation-orb-inner text-[#e60000]">
            <Sparkles size={24} />
          </div>
        </div>

        <p className="mt-7 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#e60000]">
          Building your deck
        </p>

        <h1 className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-[#e60000]">
          Creating your presentation...
        </h1>

        <p className="mt-3 text-sm text-slate-500">
          Our AI is turning your idea into a polished story.
        </p>

        <div className="mt-9 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-center gap-3">
            <div className="h-3 w-3 animate-pulse rounded-full bg-[#e60000]" />
            <span className="text-sm text-slate-600">
              Generating slides...
            </span>
          </div>
        </div>
      </div>
    </main>
  );
}

function SlideCanvas({ slide }: { slide: Slide }) {
  if (slide.kind === "title") return <div className="slide-canvas title-slide"><div className="slide-accent" /><p className="slide-kicker">{slide.kicker}</p><h1>{slide.title}</h1><p className="slide-message">{slide.message}</p><div className="slide-footer"><span>Presentation Studio</span><span>01 / 06</span></div></div>;
  if (slide.kind === "diagram") return <div className="slide-canvas"><p className="slide-kicker">{slide.kicker}</p><h2>{slide.title}</h2><p className="slide-message">{slide.message}</p><div className="pipeline"><div className="pipe-node"><Search size={16} /><b>Question</b><small>What is RAG?</small></div><ArrowRight className="pipe-arrow" size={17} /><div className="pipe-node active"><Grid2X2 size={16} /><b>Retrieve</b><small>Find context</small></div><ArrowRight className="pipe-arrow" size={17} /><div className="pipe-node"><WandSparkles size={16} /><b>Generate</b><small>Grounded answer</small></div></div><div className="slide-footer"><span>Core architecture</span><span>03 / 06</span></div></div>;
  if (slide.kind === "table") return <div className="slide-canvas"><p className="slide-kicker">{slide.kicker}</p><h2>{slide.title}</h2><p className="slide-message">{slide.message}</p><div className="comparison-table"><div className="table-row header"><span>Dimension</span><span>RAG</span><span>Fine-tuning</span></div>{[["Freshness","Real-time","Periodic"],["Attribution","Built-in","Requires work"],["Complexity","Retrieval layer","Training pipeline"]].map(row => <div className="table-row" key={row[0]}>{row.map((cell, j) => <span className={j === 0 ? "font-semibold" : ""} key={cell}>{cell}</span>)}</div>)}</div><div className="slide-footer"><span>Choose the right tool</span><span>06 / 06</span></div></div>;
  return <div className="slide-canvas"><p className="slide-kicker">{slide.kicker}</p><h2>{slide.title}</h2><p className="slide-message">{slide.message}</p><div className="insight-grid"><div><b>01</b><strong>Fresh context</strong><span>Connect to changing knowledge without retraining.</span></div><div><b>02</b><strong>Better answers</strong><span>Give models the information they need to be precise.</span></div><div><b>03</b><strong>Traceable output</strong><span>Make every response easier to trust and verify.</span></div></div><div className="slide-footer"><span>Design principles</span><span>02 / 06</span></div></div>;
}

function Editor({
  onBack,
  pptxBlob,
}: {
  onBack: () => void;
  pptxBlob: Blob | null;
}) {
  const [selected, setSelected] = useState(2);
  const [zoom, setZoom] = useState(100);

  const downloadPptx = () => {
    if (!pptxBlob) {
      console.error("No PPTX available");
      return;
    }

    const url = URL.createObjectURL(pptxBlob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "presentation.pptx";

    document.body.appendChild(link);
    link.click();

    link.remove();
    URL.revokeObjectURL(url);
  };

  const slide = slides[selected];

  return (
    <div className="editor flex min-h-0 flex-1 flex-col bg-[#f4f6fa]">
      <header className="flex h-[62px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="icon-button">
            <ChevronLeft size={17} />
          </button>

          <div className="hidden h-6 border-l border-slate-200 sm:block" />

          <Brand compact />

          <span className="hidden text-slate-300 sm:block">/</span>

          <span className="hidden max-w-[180px] truncate text-sm font-medium text-slate-700 sm:block">
            RAG for Software Engineers
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button className="editor-tool">
            <Undo2 size={16} />
          </button>

          <button className="editor-tool">
            <Redo2 size={16} />
          </button>

          <div className="mx-2 hidden h-5 border-l border-slate-200 md:block" />

          <Button
            variant="outline"
            className="hidden h-8 rounded-md px-3 text-xs sm:flex"
          >
            <RotateCcw size={14} />
            Regenerate
          </Button>

          <Button
            onClick={downloadPptx}
            disabled={!pptxBlob}
            className="h-8 rounded-md bg-[#3567d6] px-3 text-xs hover:bg-[#2d5cc8]"
          >
            <Download size={14} />

            <span className="hidden sm:inline">
              Download PPTX
            </span>
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        
      </div>
    </div>
  );
}

const CUSTOM_TEMPLATE_VALUE = "__create_custom_template__";

function TemplatePicker({
  selectedTemplateId,
  onSelectTemplateId,
}: {
  selectedTemplateId: string;
  onSelectTemplateId: (templateId: string) => void;
}) {
  const router = useRouter();
  const { defaultTemplates, customTemplates, loading } = useTemplateSummaries();
  const templates = useMemo(
    () => [...defaultTemplates, ...customTemplates],
    [defaultTemplates, customTemplates]
  );
  const selectedTemplate = templates.find(
    (template) => template.id === selectedTemplateId
  );

  const handleSelection = (value: string) => {
    onSelectTemplateId(value);
    if (value === CUSTOM_TEMPLATE_VALUE) {
      router.push("/custom-template");
    }
  };

  return (
    <div className="mt-8 w-full text-[#101828] dark:text-white">
      <div className="w-full">
        <div className="border-t border-slate-200 pt-5 dark:border-white/10">
          <label htmlFor="template-picker" className="block text-sm font-semibold text-[#344054] dark:text-zinc-200">
            Saved templates
          </label>
          <select
            id="template-picker"
            value={selectedTemplateId}
            disabled={loading}
            onChange={(event) => handleSelection(event.target.value)}
            className="mt-2 h-12 w-full rounded-xl border border-[#D0D5DD] bg-white px-4 text-sm font-medium text-[#101828] outline-none transition focus:border-[#e60000] focus:ring-4 focus:ring-[#e60000]/15 disabled:cursor-wait dark:border-white/15 dark:bg-[#171717] dark:text-white"
          >
            <option value="">
              {loading ? "Loading saved templates..." : "Select a template"}
            </option>
            {defaultTemplates.length > 0 && (
              <optgroup label="Built-in templates">
                {defaultTemplates.map((template) => (
                  <option key={template.id} value={template.id}>{template.name}</option>
                ))}
              </optgroup>
            )}
            {customTemplates.length > 0 && (
              <optgroup label="Your custom templates">
                {customTemplates.map((template) => (
                  <option key={template.id} value={template.id}>{template.name}</option>
                ))}
              </optgroup>
            )}
            <optgroup label="Create">
              <option value={CUSTOM_TEMPLATE_VALUE}>Create a custom template...</option>
            </optgroup>
          </select>

          {selectedTemplate && (
            <div className="mt-6 overflow-hidden rounded-2xl border border-[#EAECF0] dark:border-white/10">
              <div className="aspect-video p-3">
                <TemplateThumbnailPreview
                  thumbnail={selectedTemplate.thumbnail}
                  templateName={selectedTemplate.name}
                />
              </div>
              {/* <div className="flex flex-col gap-4 border-t border-[#EAECF0] p-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-base font-bold text-[#101828]">{selectedTemplate.name}</p>
                  <p className="mt-1 text-sm text-[#667085]">
                    {selectedTemplate.description || `${selectedTemplate.layout_count ?? 0} available layouts`}
                  </p>
                </div>
                <Button
                  onClick={() => router.push(`/template-preview?templateV2Id=${encodeURIComponent(selectedTemplate.id)}`)}
                  className="h-10 rounded-xl bg-[#6D5DD3] px-4 hover:bg-[#5D4FC2]"
                >
                  Open template <ChevronRight className="h-4 w-4" />
                </Button>
              </div> */}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Index() {
  const [view, setView] = useState<View>("dashboard");
  const [darkMode, setDarkMode] = useState(false);

  const [pptxBlob, setPptxBlob] = useState<Blob | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const router = useRouter();

  useEffect(() => {
    setDarkMode(window.localStorage.getItem("eand-frontend-theme") === "dark");
  }, []);

  const toggleDarkMode = () => {
    setDarkMode((current) => {
      const next = !current;
      window.localStorage.setItem("eand-frontend-theme", next ? "dark" : "light");
      return next;
    });
  };

  // ADD THIS:
  // Use this when starting a new presentation.
  // It clears any old PPTX before opening the prompt page.
  const startCreating = () => {
    setPptxBlob(null);
    setView("create");
  };

  // ADD THIS:
  // Use this when leaving the editor or going back.
  // It removes the old downloadable file.
  const backToDashboard = () => {
    setPptxBlob(null);
    setView("dashboard");
  };

//   const generatePresentation = async (prompt: string, temp: string) => {
//   try {
//     setView("generating");

//     const body = {
//       content: prompt,
//       template: temp
//     };

//     const response = await fetch("http://127.0.0.1:8000/api/v1/ppt/presentation/generate", {
//       method: "POST",
//       headers: {
//         "Content-Type": "application/json",
//       },
//       body: JSON.stringify(body),
//     });

//     if (!response.ok) {
//       console.log("Status:", response.status);
//       console.log("Status Text:", response.statusText);
//       console.log(await response.text());
//       throw new Error("Generation failed");
//     }

//     const data = await response.json();
//     router.push(`/presentation?id=${data.presentation_id}`);
//     setView("editor");
//   } catch (err) {
//     console.error(err);
//     setView("create");
//   }
// };

  const waitForSmartPresentation = (presentationId: string): Promise<void> =>
  new Promise((resolve, reject) => {
    const stream = new EventSource(
      `http://127.0.0.1:8000/api/v1/ppt/presentation/stream/${presentationId}`
    );

    stream.addEventListener("response", (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data);

        if (data.type === "error") {
          stream.close();
          reject(new Error(data.detail || "Smart generation failed"));
          return;
        }

        if (data.type === "complete") {
          stream.close();
          resolve();
        }
      } catch {
        stream.close();
        reject(new Error("Invalid presentation stream response"));
      }
    });

    stream.onerror = () => {
      stream.close();
      reject(new Error("Presentation stream disconnected before completion"));
    };
  });

const generatePresentation = async (
  prompt: string,
  temp: string,
  useEandTemplate: boolean
) => {
  try {
    setView("generating");

    // 1. Save the Smart presentation configuration.
    const response = await fetch(
      "http://127.0.0.1:8000/api/v1/ppt/presentation/create",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: prompt,
          language: "English",
          generation_mode: "smart",
          smart_template: useEandTemplate ? "eand" : undefined,
          include_title_slide: true,
          include_table_of_contents: false
        }),
      }
    );

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const { id: presentationId } = await response.json();

    // 2. Start and fully consume generation before navigating.
    await waitForSmartPresentation(presentationId);

    // 3. Open the already-complete deck.
    router.push(`/presentation?id=${presentationId}`);
    setView("editor");
  } catch (err) {
    console.error(err);
    setView("create");
  }
};

  const generateOutline = async (prompt: string, templateId: string) => {
    const content = prompt.trim();
    if (!content) {
      return;
    }

    try {
      setView("generating");

      const response = await fetch(
        getApiUrl("/api/v1/ppt/presentation/create"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content,
            language: "English",
            generation_mode: "standard",
            include_title_slide: true,
            include_table_of_contents: false,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const { id: presentationId } = await response.json();
      const params = new URLSearchParams({
        id: presentationId,
        autostart: "true",
      });
      if (templateId) {
        params.set("template", templateId);
      }

      router.push(`/outline?${params.toString()}`);
    } catch (error) {
      console.error("Failed to create outline", error);
      setView("create");
    }
  };

  const content = useMemo(() => {
    if (view === "create") {
      return (
        <CreateView
          onGenerate={generatePresentation}
          onGenerateOutline={generateOutline}
          // onGenerate={() => setView("generating")}
          onBack={backToDashboard}
          selectedTemplateId={selectedTemplateId}
          onSelectTemplateId={setSelectedTemplateId}
        />
      );
    }

    if (view === "generating") {
      return <Generating />;
    }

    if (view === "editor") {
      return (
        <Editor
          onBack={backToDashboard}
          pptxBlob={pptxBlob}
        />
      );
    }

    return <Dashboard onCreate={() => setView("create")} />;
  }, [view]);

  if (view === "editor" || view === "generating") {
    return <div className={cn("eand-frontend flex h-screen flex-col bg-white transition-colors dark:bg-[#111111]", darkMode && "dark")}><EandNavbar darkMode={darkMode} onToggleDarkMode={toggleDarkMode} />{content}</div>;
  }

  return (
    <div className={cn("eand-frontend flex min-h-screen w-full flex-col bg-white transition-colors dark:bg-[#111111]", darkMode && "dark")}>
      <EandNavbar darkMode={darkMode} onToggleDarkMode={toggleDarkMode} />
      <CreateView
          onGenerate={generatePresentation}
          onGenerateOutline={generateOutline}
          // onGenerate={() => setView("generating")}
          onBack={backToDashboard}
          selectedTemplateId={selectedTemplateId}
          onSelectTemplateId={setSelectedTemplateId}
        />
      {/* <Sidebar view={view} setView={setView} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          view={view}
          onCreate={startCreating}
        />

        {content}
      </div> */}

    </div>
  );
}
