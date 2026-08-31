"use client";

import { useRef, useState, type ChangeEvent } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowUp,
  ChevronDown,
  FileText,
  File as FileIcon,
  LayoutTemplate,
  Loader2,
  Paperclip,
  Sparkles,
  TableOfContents,
  WandSparkles,
  X,
} from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { notify } from "@/components/ui/sonner";
import { useTemplateSummaries } from "@/app/(presentation-generator)/hooks/useTemplateSummaries";
import { PresentationGenerationApi } from "@/app/(presentation-generator)/services/api/presentation-generation";
import EandLightOverlay from "@/app/components/EandLightOverlay";

const CUSTOM_TEMPLATE_VALUE = "__create_custom_template__";
const MAX_ATTACHMENTS = 8;
const DOCUMENT_ACCEPT = ".pdf,.txt,.doc,.docx,.docm,.odt,.rtf,.ppt,.pptx,.pptm,.odp,.xls,.xlsx,.xlsm,.ods,.csv,.tsv,.jpg,.jpeg,.png,.gif,.bmp,.tiff,.webp";
const ALLOWED_DOCUMENT_EXTENSIONS = new Set(DOCUMENT_ACCEPT.split(","));

type GenerationMode = "standard" | "eand" | "outline" | null;

export default function GenerationPageClient() {
  const router = useRouter();
  const { defaultTemplates, customTemplates, loading: templatesLoading } = useTemplateSummaries();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [prompt, setPrompt] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [generationMode, setGenerationMode] = useState<GenerationMode>(null);

  const handleTemplateSelection = (value: string) => {
    setSelectedTemplateId(value);
    if (value === CUSTOM_TEMPLATE_VALUE) router.push("/custom-template");
  };

  const addFiles = (candidates: File[]) => {
    const allowedFiles = candidates.filter((file) => {
      const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      return ALLOWED_DOCUMENT_EXTENSIONS.has(extension);
    });
    if (allowedFiles.length !== candidates.length) {
      notify.warning("Some files were not added", "Attach PDF, Office, spreadsheet, text, or image files.");
    }
    const nextFiles = [...files, ...allowedFiles].slice(0, MAX_ATTACHMENTS);
    if (files.length + allowedFiles.length > MAX_ATTACHMENTS) {
      notify.warning("Attachment limit reached", `You can attach up to ${MAX_ATTACHMENTS} source files.`);
    }
    setFiles(nextFiles);
  };

  const handleFilesSelected = (event: ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files ?? []));
    event.currentTarget.value = "";
  };

  const uploadDocuments = async () => {
    if (files.length === 0) return [];
    const uploadedFiles = await PresentationGenerationApi.uploadDoc(files);
    if (!Array.isArray(uploadedFiles) || uploadedFiles.some((path) => typeof path !== "string")) {
      throw new Error("The document upload response was invalid.");
    }
    const decomposedFiles = await PresentationGenerationApi.decomposeDocuments(uploadedFiles, "English");
    if (!Array.isArray(decomposedFiles)) throw new Error("The documents could not be processed.");
    const documentPaths = decomposedFiles
      .map((document) => document && typeof document === "object" && "file_path" in document ? (document as { file_path?: unknown }).file_path : null)
      .filter((filePath): filePath is string => typeof filePath === "string");
    if (documentPaths.length === 0) throw new Error("We could not read the attached documents.");
    return documentPaths;
  };

  const getGenerationContent = () => prompt.trim() || (files.length > 0 ? "Create a presentation from the attached source documents." : "");

  const generateDeck = async (useEandTemplate: boolean) => {
    const content = getGenerationContent();
    if (!content) {
      notify.error("Add a brief or source files", "Tell e& Present what you want to present, or attach source documents.");
      return;
    }

    setGenerationMode(useEandTemplate ? "eand" : "standard");
    try {
      const filePaths = await uploadDocuments();
      let smartBrandColors: string[] | undefined;
      if (useEandTemplate) {
        const referenceDeck = files.find((file) => file.name.toLowerCase().endsWith(".pptx"));
        if (referenceDeck) {
          try {
            const { colors } = await PresentationGenerationApi.extractPptxColorPalette(referenceDeck);
            if (colors && colors.length > 0) smartBrandColors = colors;
          } catch {
            // Non-fatal: fall back to the default e& palette rather than blocking generation.
          }
        }
      }
      const presentation = await PresentationGenerationApi.createPresentation({
        content,
        n_slides: null,
        file_paths: filePaths,
        language: "English",
        generation_mode: "smart",
        smart_template: useEandTemplate ? "eand" : undefined,
        smart_brand_colors: smartBrandColors,
        include_title_slide: true,
        include_table_of_contents: false,
      });
      router.replace(`/presentation?id=${presentation.id}&stream=true&type=smart`);
    } catch (error) {
      notify.error("Could not start generation", error instanceof Error ? error.message : "Please try again.");
      setGenerationMode(null);
    }
  };

  const generateOutline = async () => {
    const content = getGenerationContent();
    if (!content) {
      notify.error("Add a brief or source files", "Tell e& Present what you want to present, or attach source documents.");
      return;
    }

    setGenerationMode("outline");
    try {
      const filePaths = await uploadDocuments();
      const presentation = await PresentationGenerationApi.createPresentation({
        content,
        n_slides: null,
        file_paths: filePaths,
        language: "English",
        generation_mode: "standard",
        include_title_slide: true,
        include_table_of_contents: false,
      });
      const params = new URLSearchParams({ id: presentation.id, autostart: "true" });
      if (selectedTemplateId) params.set("template", selectedTemplateId);
      router.push(`/outline?${params.toString()}`);
    } catch (error) {
      notify.error("Could not create outline", error instanceof Error ? error.message : "Please try again.");
      setGenerationMode(null);
    }
  };

  const isGenerating = generationMode !== null;

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#fcfcfe] px-5 py-6 text-[#151515] sm:px-8">
      <EandLightOverlay />
      <header className="relative mx-auto flex w-full max-w-[1240px] items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg outline-none transition-opacity hover:opacity-75 focus-visible:ring-2 focus-visible:ring-[#e60000] focus-visible:ring-offset-4">
          <Image src="/eand-logo.png" alt="e&" width={42} height={42} className="h-8 w-8 object-contain" />
          <span className="hidden text-sm font-semibold tracking-[-0.02em] text-[#252525] sm:block">Presentation Studio</span>
        </Link>
        <Link href="/" className="rounded-full border border-[#ebd7d7] bg-white px-4 py-2 text-sm font-semibold text-[#b80000] shadow-sm transition-colors hover:border-[#e60000] hover:bg-[#fff8f8]">Back to dashboard</Link>
      </header>

      <section className="relative mx-auto flex w-full max-w-[1080px] flex-col items-center pb-14 pt-[min(16vh,130px)] text-center">
        {/* <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-[#f2dddd] bg-[#fff8f8] px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-[#d60000]"><Sparkles className="h-3.5 w-3.5" /> e&amp; AI workspace</div> */}
        <h1 className="font-serif text-[45px] font-semibold leading-[0.98] tracking-[-0.045em] text-[#131313] sm:text-[62px]">
          Hi, I am <span className="text-[#e60000]">e&amp; Present</span>
        </h1>
        <p className="mt-6 max-w-[700px] font-serif text-[20px] leading-8 text-[#7c7171] sm:text-[24px]">Your AI workspace for presentations that make every idea matter.</p>

        <div className="mt-11 w-full rounded-[22px] border border-[#dfd9d9] bg-white p-4 text-left shadow-[0_22px_55px_rgba(43,23,23,0.08)] transition-shadow focus-within:shadow-[0_24px_65px_rgba(230,0,0,0.13)] sm:p-5">
          <label htmlFor="presentation-brief" className="sr-only">Presentation brief</label>
          <Textarea id="presentation-brief" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask e& Present to make a presentation, or describe a task…" className="min-h-[150px] resize-none border-0 bg-transparent px-1 py-1.5 text-[17px] leading-7 text-[#1f1f1f] shadow-none placeholder:text-[#aaa2a2] focus-visible:ring-0 sm:min-h-[168px]" />

          {files.length > 0 && (
            <ul className="mb-3 flex flex-wrap gap-2" aria-label="Attached source files">
              {files.map((file, index) => (
                <li key={`${file.name}-${file.size}-${index}`} className="inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border border-[#f0d5d5] bg-[#fff8f8] px-2.5 text-xs font-medium text-[#5d4646]">
                  <FileIcon className="h-3.5 w-3.5 shrink-0 text-[#e60000]" />
                  <span className="max-w-[180px] truncate" title={file.name}>{file.name}</span>
                  <button type="button" onClick={() => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))} aria-label={`Remove ${file.name}`} disabled={isGenerating} className="rounded-full p-0.5 text-[#9c7777] transition-colors hover:bg-[#f3dede] hover:text-[#b80000] disabled:cursor-not-allowed"><X className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-col gap-3 border-t border-[#f0eded] pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="inline-flex h-9 items-center gap-2 rounded-full bg-[#f8f6f6] px-3 text-sm font-semibold text-[#3c3636]"><FileText className="h-4 w-4 text-[#e60000]" /> Presentation</span>
              <input ref={fileInputRef} type="file" accept={DOCUMENT_ACCEPT} multiple className="hidden" onChange={handleFilesSelected} />
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={isGenerating || files.length >= MAX_ATTACHMENTS} className="inline-flex h-9 items-center gap-2 rounded-full border border-[#eee6e6] bg-white px-3 text-sm font-semibold text-[#5a4e4e] transition-colors hover:border-[#e6bcbc] hover:bg-[#fffafa] disabled:cursor-not-allowed disabled:opacity-55"><Paperclip className="h-4 w-4 text-[#d60000]" />{files.length > 0 ? `Attach files (${files.length})` : "Attach files"}</button>
              <label className="relative inline-flex h-9 items-center min-w-0">
                <LayoutTemplate className="pointer-events-none absolute inset-y-0 left-3 my-auto h-4 w-4 text-[#9a7f7f]" />
                <select value={selectedTemplateId} disabled={templatesLoading || isGenerating} onChange={(event) => handleTemplateSelection(event.target.value)} className="h-9 max-w-[215px] appearance-none rounded-full border border-[#eee6e6] bg-white py-0 pl-9 pr-8 text-sm font-medium text-[#5a4e4e] outline-none transition focus:border-[#e60000] disabled:cursor-wait disabled:opacity-60">
                  <option value="">{templatesLoading ? "Loading templates…" : "Choose a template"}</option>
                  {defaultTemplates.length > 0 && <optgroup label="Built-in templates">{defaultTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</optgroup>}
                  {customTemplates.length > 0 && <optgroup label="Your templates">{customTemplates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</optgroup>}
                  <optgroup label="Create"><option value={CUSTOM_TEMPLATE_VALUE}>Create a custom template…</option></optgroup>
                </select>
                <ChevronDown className="pointer-events-none absolute inset-y-0 right-3 my-auto h-3.5 w-3.5 text-[#8d8080]" />
              </label>
              {selectedTemplateId && selectedTemplateId !== CUSTOM_TEMPLATE_VALUE && (
                <span className="text-xs text-[#9a8a8a]">Only used by Outline — Generate ignores it</span>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              <button type="button" disabled={isGenerating} onClick={() => void generateOutline()} className="inline-flex h-10 items-center gap-2 rounded-full px-3 text-sm font-semibold text-[#625656] transition-colors hover:bg-[#f7f3f3] disabled:cursor-wait disabled:opacity-60"><TableOfContents className="h-4 w-4" />{generationMode === "outline" ? "Starting…" : "Outline"}</button>
              <button type="button" disabled={isGenerating} onClick={() => void generateDeck(false)} className="inline-flex h-10 items-center gap-2 rounded-full border border-[#e7dddd] bg-white px-4 text-sm font-semibold text-[#3a3333] transition-colors hover:border-[#cfb4b4] hover:bg-[#fffafa] disabled:cursor-wait disabled:opacity-60"><WandSparkles className="h-4 w-4 text-[#d60000]" />{generationMode === "standard" ? "Starting…" : "Generate Standard"}<ArrowUp className="h-4 w-4 text-[#d60000]" /></button>
              <button type="button" disabled={isGenerating} onClick={() => void generateDeck(true)} className="inline-flex h-10 items-center gap-2 rounded-full bg-[#e60000] px-4 text-sm font-semibold text-white shadow-[0_6px_16px_rgba(230,0,0,0.22)] transition-all hover:bg-[#bc0000] hover:shadow-[0_8px_20px_rgba(230,0,0,0.3)] disabled:cursor-wait disabled:opacity-65"><span className="hidden sm:inline">{generationMode === "eand" ? "Starting…" : "Generate e& deck"}</span><span className="sm:hidden">{generationMode === "eand" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-5 w-5" />}</span><span className="hidden sm:block"><ArrowUp className="h-4 w-4" /></span></button>
            </div>
          </div>
        </div>

        <p className="mt-5 text-sm text-[#8c8383]">Try: “Create a 10-slide deck on e&amp;’s green technology strategy for senior leadership.”</p>
      </section>
    </main>
  );
}
