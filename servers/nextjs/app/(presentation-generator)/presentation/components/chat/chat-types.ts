import type { TemplateV2SurfaceSelectedDetail } from "@/components/slide-editor/events/events";
import type { TemplateV2Layout } from "@/components/slide-editor/importing/template-v2-import";
import type {
  ChatAttachment,
  ChatConversationSummary,
  ChatHistoryMessage,
  ChatMessageResponse,
  ChatStreamHandlers,
} from "../../../services/api/chat";

export type AssistantActivity = {
  id: string;
  label: string;
  kind?: string;
  round?: number;
  tool?: string;
  state: "running" | "success" | "error" | "info";
};

export type ChatEditPreview = {
  originalSlides: unknown[];
  modifiedSlides?: unknown[];
  slideIndices: number[];
  changeCount: number;
};

export type ChatLayoutPreview = {
  layout: TemplateV2Layout;
  layoutId?: string | null;
  slideIndex?: number | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  toolCalls?: string[];
  activity?: AssistantActivity[];
  layoutPreview?: ChatLayoutPreview;
  editPreview?: ChatEditPreview;
};

export type SubmitMessageOptions = {
  backendContext?: string;
  layoutPreview?: ChatLayoutPreview;
};

export type PastedChatImage = {
  id: string;
  name: string;
  url: string;
  file?: File;
  extractedText?: string;
};

export type ChatLink = {
  id: string;
  url: string;
};

export type ChatDocumentAttachment = {
  id: string;
  name: string;
  filePath: string;
  mimeType?: string;
};

export type ChatApiAdapter = {
  listConversations: (resourceId: string) => Promise<ChatConversationSummary[]>;
  getHistory: (
    resourceId: string,
    conversationId: string,
  ) => Promise<{ messages: ChatHistoryMessage[] }>;
  deleteConversation: (
    resourceId: string,
    conversationId: string,
  ) => Promise<void>;
  streamMessage: (
    payload: {
      resourceId: string;
      message: string;
      conversation_id?: string;
      attachments?: ChatAttachment[];
    },
    handlers?: ChatStreamHandlers,
    options?: { signal?: AbortSignal },
  ) => Promise<ChatMessageResponse>;
};

export type ChatProps = {
  presentationId: string;
  presentationData?: unknown;
  resourceId?: string;
  chatAdapter?: ChatApiAdapter;
  conversationStorageScope?: string;
  resourceLabel?: string;
  variant?: "presentation" | "outline" | "template-v2";
  useEditorLayout?: boolean;
  inputDisabled?: boolean;
  currentSlide?: number;
  selectedTemplateV2Target?: TemplateV2SurfaceSelectedDetail["selection"];
  onClearChatSlideReference?: () => void;
  onClearChatTargetReference?: () => void;
  onBeforeSend?: () => Promise<void> | void;
  onPresentationChanged?: () => Promise<void> | void;
  onChatMutationStateChange?: (isMutating: boolean) => void;
  onAgentSlideFocus?: (focus: {
    slideIndex: number;
    eventId: string;
    tool?: string;
    status?: string;
    isMutatingTool: boolean;
  }) => void;
  onChatSendingStateChange?: (isSending: boolean) => void;
  onFollowModeChange?: (isEnabled: boolean) => void;
};

export type AssistantPromptMetrics = {
  startedAt: number;
  attachmentImageCount: number;
  attachmentDocumentCount: number;
  linkCount: number;
  mutatingToolCount: number;
  readToolCount: number;
  uniqueTools: Set<string>;
  mutatedSlides: Set<number>;
};
