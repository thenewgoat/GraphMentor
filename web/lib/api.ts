/** API client — typed fetch wrappers for all backend endpoints. */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Type imports
import type {
  Course,
  NodeEdge,
  DocumentInfo,
  ReferenceInfo,
  PageData,
  OrganizeSuggestion,
} from "./types";

export type { Course };

// API response types
export interface GraphNode {
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
  pages: PageData[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: NodeEdge[];
}

// Courses
export const getCourses = () => request<Course[]>("/courses");
export const createCourse = (title: string) =>
  request<Course>("/courses", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
export const getCourse = (id: string) => request<Course>(`/courses/${id}`);
export const deleteCourse = (courseId: string) =>
  request<void>(`/courses/${courseId}`, { method: "DELETE" });
export const getGraph = (courseId: string) =>
  request<GraphData>(`/courses/${courseId}/graph`);

// Upload (multipart — no JSON Content-Type)
export async function uploadPdf(file: File, title: string, courseId?: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  if (courseId) form.append("course_id", courseId);
  const res = await fetch(`${API_URL}/ingest/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

// Extract
export const extractTopics = (courseId: string, documentId: string) =>
  request<Record<string, unknown>>(
    `/extract/topics/${courseId}?document_id=${documentId}`,
    { method: "POST" }
  );

export const extractAllTopics = (courseId: string) =>
  request<{ docs_extracted: number; nodes_created: number; edges_created: number }>(
    `/extract/topics/${courseId}`,
    { method: "POST" }
  );

// Documents
export const getDocuments = (courseId: string) =>
  request<DocumentInfo[]>(`/courses/${courseId}/documents`);

export const deleteDocument = (courseId: string, docId: string) =>
  request<void>(`/courses/${courseId}/documents/${docId}`, { method: "DELETE" });

// References
export const getReferences = (courseId: string) =>
  request<ReferenceInfo[]>(`/courses/${courseId}/references`);

export const createReference = (courseId: string, data: Omit<ReferenceInfo, "id">) =>
  request<{ id: string }>(`/courses/${courseId}/references`, {
    method: "POST",
    body: JSON.stringify(data),
  });

export const deleteReference = (courseId: string, refId: string) =>
  request<void>(`/courses/${courseId}/references/${refId}`, { method: "DELETE" });

// Enrich & Organize
export const enrichCourse = (courseId: string) =>
  request<{ nodes_enriched: number; nodes_skipped: number }>(
    `/extract/enrich/${courseId}`,
    { method: "POST" }
  );

export const organizeCourse = (courseId: string) =>
  request<{ suggestions: OrganizeSuggestion[] }>(
    `/extract/organize/${courseId}`,
    { method: "POST" }
  );

export const applyOrganization = (courseId: string, suggestionIds: number[]) =>
  request<{ applied: number }>(
    `/extract/organize/${courseId}/apply`,
    { method: "POST", body: JSON.stringify({ suggestion_ids: suggestionIds }) }
  );

// Node CRUD
export const createNode = (courseId: string, title: string) =>
  request<GraphNode>(`/courses/${courseId}/nodes`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });

export const updateNode = (courseId: string, nodeId: string, data: { title?: string }) =>
  request<GraphNode>(`/courses/${courseId}/nodes/${nodeId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteNode = (courseId: string, nodeId: string) =>
  request<void>(`/courses/${courseId}/nodes/${nodeId}`, { method: "DELETE" });

// Edge CRUD
export const createEdge = (
  courseId: string,
  parentId: string,
  childId: string,
  edgeCategory: string = "dependency",
  edgeLabel: string = "relates to",
) =>
  request<NodeEdge>(`/courses/${courseId}/edges`, {
    method: "POST",
    body: JSON.stringify({ parent_id: parentId, child_id: childId, edge_category: edgeCategory, edge_label: edgeLabel }),
  });

export const deleteEdge = (courseId: string, parentId: string, childId: string) =>
  request<void>(`/courses/${courseId}/edges/${parentId}/${childId}`, { method: "DELETE" });

// Game
export const launchGame = (courseId: string, nodeId: string) =>
  request<{ status: string }>(`/game/launch/${courseId}/${nodeId}`, {
    method: "POST",
  });
