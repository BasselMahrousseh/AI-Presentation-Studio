import { PresentationChatApi } from "../../../services/api/chat";
import type { ChatApiAdapter } from "./chat-types";

export const presentationChatAdapter: ChatApiAdapter = {
  listConversations: (resourceId) =>
    PresentationChatApi.listConversations(resourceId),
  getHistory: (resourceId, conversationId) =>
    PresentationChatApi.getHistory(resourceId, conversationId),
  deleteConversation: (resourceId, conversationId) =>
    PresentationChatApi.deleteConversation(resourceId, conversationId),
  streamMessage: (payload, handlers, options) =>
    PresentationChatApi.streamMessage(
      {
        presentation_id: payload.resourceId,
        message: payload.message,
        conversation_id: payload.conversation_id,
        attachments: payload.attachments,
      },
      handlers,
      options,
    ),
};
