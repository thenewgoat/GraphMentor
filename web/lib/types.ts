/** Shared TypeScript types mirroring backend models and API responses. */

// === Enums / Union Types ===

export type EdgeCategory = "dependency" | "association" | "hierarchy";
export type LearningState = "baseline" | "learning" | "review" | "exam";
export type IngestionStatus = "pending" | "processing" | "complete" | "failed" | "graph_ready";
export type QuestionType = "multiple_choice" | "short_answer";
export type Difficulty = "easy" | "medium" | "hard";
export type AttemptContext = "baseline" | "quiz" | "exam";

// === Core Models ===

export interface Course {
  id: string;
  title: string;
  topic_title: string | null;
  description: string | null;
  mastery_threshold: number;
  time_decay_lambda: number;
  max_follow_ups_per_session: number;
  topic_radius: number;
  ingestion_status: IngestionStatus;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface Node {
  id: string;
  course_id: string;
  title: string;
  parent_ids: string[];
  child_ids: string[];
  depth: number;
  order_index: number;
  node_type: "concept" | "group";
  supplementary_content: string | null;
  application_examples: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface NodeEdge {
  parent_id: string;
  child_id: string;
  edge_category: EdgeCategory;
  edge_label: string;
}

export interface Student {
  id: string;
  course_id: string;
  display_name: string;
  current_node_id: string | null;
  learning_state: LearningState;
  session_interaction_count: number;
  created_at: string;
  updated_at: string;
}

export interface StudentNodeState {
  student_id: string;
  node_id: string;
  mastery_score: number;
  accuracy: number;
  confidence_score: number;
  teach_completion_score: number;
  mistake_classification: string[] | null;
  last_reviewed: string | null;
  total_attempts: number;
  correct_attempts: number;
}

export interface Question {
  id: string;
  node_id: string;
  question_type: QuestionType;
  question_text: string;
  options: McOption[] | null;
  correct_answer: string;
  expected_time_seconds: number;
  difficulty: Difficulty;
  source_chunk_ids: string[];
  created_at: string;
}

export interface McOption {
  label: string;
  text: string;
  is_correct: boolean;
}

export interface Attempt {
  id: string;
  student_id: string;
  question_id: string;
  node_id: string;
  answer: string;
  is_correct: boolean;
  response_time_seconds: number;
  attempt_context: AttemptContext;
  created_at: string;
}

// === New types for pipeline overhaul ===

export type DocIngestionStatus = "pending" | "processing" | "complete" | "failed";

export interface DocumentInfo {
  id: string;
  title: string;
  filename: string;
  upload_order: number;
  page_count: number | null;
  ingestion_status: DocIngestionStatus;
  created_at: string;
}

export interface PageData {
  id: string;
  page_number: number;
  global_page: number;
  slide_title: string | null;
  body: string;
  document_title: string;
}

export interface ReferenceInfo {
  id: string;
  ref_type: "book" | "url";
  title: string;
  author: string | null;
  isbn: string | null;
  url: string | null;
}

export interface OrganizeSuggestion {
  id: number;
  type: "MERGE" | "SPLIT" | "REORDER" | "REPARENT" | "CREATE_GROUP" | "DISSOLVE_GROUP";
  node_titles: string[];
  merged_title?: string;
  group_title?: string;
  children?: string[];
  new_parent_title?: string;
  new_order_index?: number;
  split_into?: { title: string; page_ids: string[] }[];
  reasoning: string;
}
