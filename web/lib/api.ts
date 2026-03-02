const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

// Courses
export const getCourses = () => request<Course[]>("/courses");
export const getCourse = (id: string) => request<Course>(`/courses/${id}`);
export const getGraph = (courseId: string) =>
  request<GraphData>(`/courses/${courseId}/graph`);

// Upload (multipart — no JSON Content-Type)
export async function uploadPdf(file: File, title: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  const res = await fetch(`${API_URL}/ingest/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

// Extract
export const extractTopics = (courseId: string) =>
  request<Record<string, unknown>>(`/extract/topics/${courseId}`, { method: "POST" });

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
  edgeType: string = "prerequisite",
) =>
  request<NodeEdge>(`/courses/${courseId}/edges`, {
    method: "POST",
    body: JSON.stringify({ parent_id: parentId, child_id: childId, edge_type: edgeType }),
  });

export const deleteEdge = (courseId: string, parentId: string, childId: string) =>
  request<void>(`/courses/${courseId}/edges/${parentId}/${childId}`, { method: "DELETE" });

// Type imports (re-exported from types.ts)
import type { Course, NodeEdge } from "./types";

// Additional types for API responses
export interface SentenceData {
  id: string;
  page: number;
  position: number;
  slide_title: string | null;
  text: string;
}

export interface GraphNode {
  id: string;
  course_id: string;
  title: string;
  parent_ids: string[];
  child_ids: string[];
  depth: number;
  order_index: number;
  application_examples: Record<string, unknown> | null;
  sentences: SentenceData[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: NodeEdge[];
}
