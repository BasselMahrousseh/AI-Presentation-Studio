import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Grip } from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { marked } from "marked";

import { Textarea } from "@/components/ui/textarea";

interface OutlineItemProps {
  slideOutline: {
    content: string;
  };
  id: string;
  index: number;
  isStreaming: boolean;
  isActiveStreaming?: boolean;
  isStableStreaming?: boolean;
  onUpdate?: (newContent: string) => void;
}

const outlineMarkdownClassName =
  "prose prose-sm max-w-none flex-1 font-syne text-sm font-normal leading-6 text-[#526078] [overflow-wrap:anywhere] [&>*]:!my-0 [&>*+*]:!mt-2 [&_h1]:text-[18px] [&_h1]:font-semibold [&_h1]:leading-6 [&_h1]:text-[#172a5c] [&_h2]:text-[18px] [&_h2]:font-semibold [&_h2]:leading-6 [&_h2]:text-[#172a5c] [&_h3]:text-[16px] [&_h3]:font-semibold [&_h3]:leading-6 [&_h3]:text-[#172a5c] [&_p]:text-sm [&_p]:font-normal [&_p]:leading-6 [&_p]:text-[#526078] [&_strong]:font-semibold [&_strong]:text-[#172a5c] [&_ul]:!my-0 [&_ul]:list-none [&_ul]:space-y-1 [&_ul]:pl-0 [&_ul_li]:my-0 [&_ul_li]:bg-[url('/figma/outline-check.svg')] [&_ul_li]:bg-[length:16px_16px] [&_ul_li]:bg-[position:left_4px] [&_ul_li]:bg-no-repeat [&_ul_li]:pl-6 [&_ul_li]:text-sm [&_ul_li]:font-normal [&_ul_li]:leading-6 [&_ul_li]:text-[#526078]";

export function OutlineItem({
  id,
  index,
  slideOutline,
  isStreaming,
  isActiveStreaming = false,
  isStableStreaming = false,
  onUpdate,
}: OutlineItemProps) {
  useEffect(() => {
    if (isStreaming) {
      const outlineItem = document.getElementById(`outline-item-${index}`);
      if (outlineItem) {
        outlineItem.scrollIntoView({
          behavior: "smooth",
          block: "center",
          inline: "nearest",
        });
      }
    }
  }, [index, isStreaming, slideOutline.content]);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled: isStreaming });

  const style = {
    transform: CSS.Transform.toString(
      transform ? { ...transform, scaleX: 1, scaleY: 1 } : null
    ),
    transition,
  };

  const editorRef = useRef<HTMLTextAreaElement>(null);
  const throttleRef = useRef<number | null>(null);
  const [markdownDraft, setMarkdownDraft] = useState(
    slideOutline.content || ""
  );
  const [isEditingMarkdown, setIsEditingMarkdown] = useState(false);
  const [renderedHtml, setRenderedHtml] = useState<string>("");

  useEffect(() => {
    setMarkdownDraft(slideOutline.content || "");
  }, [slideOutline.content]);

  useEffect(() => {
    if (!isEditingMarkdown) return;
    const editor = editorRef.current;
    if (!editor) return;

    editor.focus();
    const end = editor.value.length;
    editor.setSelectionRange(end, end);
  }, [isEditingMarkdown]);

  const handleMarkdownBlur = () => {
    if (markdownDraft !== slideOutline.content) {
      onUpdate?.(markdownDraft);
    }
    setIsEditingMarkdown(false);
  };

  const handleStartMarkdownEdit = () => {
    setMarkdownDraft(slideOutline.content || "");
    setIsEditingMarkdown(true);
  };

  const handleMarkdownKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab") return;

    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const updatedValue = `${markdownDraft.slice(
      0,
      start
    )}\t${markdownDraft.slice(end)}`;

    setMarkdownDraft(updatedValue);
    requestAnimationFrame(() => {
      target.selectionStart = target.selectionEnd = start + 1;
    });
  };

  useEffect(() => {
    if (!isStreaming || !isActiveStreaming) return;
    const content = slideOutline.content || "";

    if (throttleRef.current) {
      window.clearTimeout(throttleRef.current);
    }
    throttleRef.current = window.setTimeout(() => {
      try {
        setRenderedHtml(marked.parse(content) as string);
      } catch {
        setRenderedHtml("");
      }
    }, 60);

    return () => {
      if (throttleRef.current) {
        window.clearTimeout(throttleRef.current);
      }
    };
  }, [isStreaming, isActiveStreaming, slideOutline.content]);

  const stableHtml = useMemo(() => {
    if (!isStreaming || isActiveStreaming) return null;
    if (!isStableStreaming) return null;
    try {
      return marked.parse(slideOutline.content || "") as string;
    } catch {
      return null;
    }
  }, [isStreaming, isActiveStreaming, isStableStreaming, slideOutline.content]);

  const previewHtml = useMemo(() => {
    if (isStreaming) return "";
    try {
      return marked.parse(slideOutline.content || "", {
        breaks: true,
        gfm: true,
      }) as string;
    } catch {
      return "";
    }
  }, [isStreaming, slideOutline.content]);

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`group relative mb-3 overflow-hidden rounded-2xl border bg-white px-4 py-4 font-syne transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_12px_26px_rgba(16,39,80,0.10)] sm:px-5 sm:py-5 ${
        isEditingMarkdown
          ? "border-[#e60000] shadow-[0_8px_20px_rgba(230,0,0,0.12)]"
          : "border-[#e6e9ef] shadow-[0_3px_8px_rgba(16,39,80,0.04)]"
      } ${isDragging ? "opacity-50" : ""}`}
    >
      <div className="flex items-start gap-3 sm:gap-4">
        <div
          {...attributes}
          {...listeners}
          aria-label={`Move slide ${index}`}
          className="relative flex h-10 w-10 shrink-0 touch-none select-none items-center justify-center rounded-xl bg-[#fff1f1] text-sm font-semibold text-[#e60000] outline-none ring-1 ring-[#ffd4d4] cursor-grab active:cursor-grabbing"
        >
          <span>{String(index).padStart(2, "0")}</span>
          <Grip aria-hidden="true" className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-white p-0.5 text-[#8992a5] shadow-sm" />
        </div>

        <div
          id={`outline-item-${index}`}
          className="flex min-w-0 basis-full flex-col gap-[10px]"
        >
          {isStreaming ? (
            isActiveStreaming ? (
              <div
                className={outlineMarkdownClassName}
                dangerouslySetInnerHTML={{ __html: renderedHtml || "" }}
              />
            ) : stableHtml ? (
              <div
                className={outlineMarkdownClassName}
                dangerouslySetInnerHTML={{ __html: stableHtml }}
              />
            ) : (
              <p className="flex-1 text-base font-normal text-[#26364D]">
                {slideOutline.content || ""}
              </p>
            )
          ) : isEditingMarkdown ? (
            <Textarea
              ref={editorRef}
              value={markdownDraft}
              onChange={(event) => setMarkdownDraft(event.target.value)}
              onBlur={handleMarkdownBlur}
              onKeyDown={handleMarkdownKeyDown}
              spellCheck={false}
              placeholder="Enter markdown content here..."
              className="min-h-[140px] resize-y rounded-[8px] border-[#D8D8DF] bg-[#FBFBFC] px-3 py-3 font-mono text-[13px] leading-6 text-[#191919] shadow-none focus-visible:border-[#E60000] focus-visible:ring-2 focus-visible:ring-[#E60000]/20"
            />
          ) : (
            <div
              role="button"
              tabIndex={0}
              aria-label={`Edit slide ${index} markdown`}
              onClick={handleStartMarkdownEdit}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  handleStartMarkdownEdit();
                }
              }}
              className={`${outlineMarkdownClassName} min-h-[60px] w-full cursor-text rounded-[8px] px-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#E60000]/25`}
              dangerouslySetInnerHTML={{ __html: previewHtml }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
