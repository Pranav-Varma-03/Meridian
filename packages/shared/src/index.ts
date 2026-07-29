/**
 * Exact transport contracts shared by Meridian's API consumers.
 *
 * These types intentionally retain the FastAPI JSON field names. UI code can map them
 * to presentation-specific view models at its own boundary without obscuring the API
 * contract or accidentally changing serialized request fields.
 */

export type DocumentStatus = "queued" | "processing" | "ready" | "failed";
export type IngestionJobStatus = DocumentStatus;
export type RetrievalScopeMode = "all" | "collections";
export type ReingestionReason =
  | "manual_repair"
  | "model_migration"
  | "chunking_change";

export interface ApiErrorDetail {
  code: string;
  message: string;
  request_id: string;
  details?: Record<string, unknown> | null;
}

export interface ApiErrorEnvelope {
  error: ApiErrorDetail;
}

export interface PaginationResponse {
  total: number;
}

export interface IngestionJobResponse {
  id: string;
  document_id: string;
  status: IngestionJobStatus;
  attempts: number;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface DocumentResponse {
  id: string;
  filename: string;
  status: DocumentStatus;
  collection_id: string | null;
  created_at: string;
  chunk_count: number | null;
  file_size: number;
}

export interface DocumentListResponse extends PaginationResponse {
  documents: DocumentResponse[];
}

export interface DocumentUploadAccepted {
  job_id: string;
  document_id: string;
  filename: string | null;
  status: IngestionJobStatus;
  deduplicated: boolean;
  reused_existing_job: boolean;
  message: string;
}

export interface DocumentDeleteResponse {
  message: string;
}

export interface CollectionResponse {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  created_at: string;
}

export interface CollectionListResponse extends PaginationResponse {
  collections: CollectionResponse[];
}

export interface CollectionCreateRequest {
  name: string;
  description?: string | null;
}

export interface CollectionUpdateRequest {
  name?: string;
  description?: string | null;
}

export interface RetrievalScopeRequest {
  mode: RetrievalScopeMode;
  collection_ids?: string[];
}

export interface RetrievalScopeResponse {
  mode: RetrievalScopeMode;
  collection_ids: string[];
  version: number;
}

export interface ConversationScopeEventResponse extends RetrievalScopeResponse {
  effective_from_sequence: number;
}

export interface ChatRequest {
  query: string;
  conversation_id?: string;
  /** Legacy compatibility only. New web code must use retrieval_scope. */
  collection_ids?: string[];
  retrieval_scope?: RetrievalScopeRequest;
}

export interface SourceCitation {
  document_id: string;
  generation: number;
  chunk_id: string;
  filename: string;
  page_number: number | null;
  section_heading: string | null;
  excerpt: string;
  content_sha256: string;
  score: number;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: { sources?: SourceCitation[] } & Record<string, unknown>;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  updated_at: string;
  retrieval_scope: RetrievalScopeResponse;
}

export interface ConversationListResponse extends PaginationResponse {
  conversations: ConversationSummary[];
}

export interface ConversationResponse {
  id: string;
  title: string | null;
  messages: ConversationMessage[];
  retrieval_scope: RetrievalScopeResponse;
  scope_events: ConversationScopeEventResponse[];
}

export interface ChatTextEvent {
  type: "text";
  content: string;
}

export interface ChatSourcesEvent {
  type: "sources";
  content: SourceCitation[];
}

export interface ChatErrorEvent {
  type: "error";
  message: string;
}

export interface ChatDoneEvent {
  type: "done";
  conversation_id: string;
  retrieval_scope: RetrievalScopeResponse;
}

export type ChatStreamEvent =
  | ChatTextEvent
  | ChatSourcesEvent
  | ChatErrorEvent
  | ChatDoneEvent;

export interface UserProvisionResponse {
  id: string;
  auth_subject: string;
  email: string | null;
  created_at: string;
}
