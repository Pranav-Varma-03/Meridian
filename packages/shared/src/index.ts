// Shared types between frontend and backend

export interface Document {
  id: string;
  filename: string;
  status: "queued" | "processing" | "ready" | "failed";
  collectionId?: string;
  createdAt: string;
  chunkCount?: number;
  fileSize: number;
}

export interface Collection {
  id: string;
  name: string;
  description?: string;
  documentCount: number;
  createdAt: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  timestamp: string;
}

export interface Source {
  documentId: string;
  filename: string;
  pageNumber?: number;
  chunkText: string;
  score: number;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  collectionIds?: string[];
  createdAt: string;
  updatedAt: string;
}

export type RetrievalScope =
  | { mode: "all"; collectionIds: []; version: number }
  | { mode: "collections"; collectionIds: string[]; version: number };

export type ConversationScopeEvent = RetrievalScope & {
  effectiveFromSequence: number;
};

export interface ChatDoneEvent {
  type: "done";
  conversationId: string;
  retrievalScope: RetrievalScope;
}

export interface ApiError {
  error: string;
  message: string;
  code: string;
}
