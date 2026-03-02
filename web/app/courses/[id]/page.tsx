/** Course detail page — documents, references, enrich, and organize actions. */
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Course } from "@/lib/types";
import { getCourse, enrichCourse, organizeCourse, applyOrganization } from "@/lib/api";
import type { OrganizeSuggestion } from "@/lib/types";
import StatusBadge from "@/components/StatusBadge";
import DocumentList from "@/components/DocumentList";
import ReferenceList from "@/components/ReferenceList";

type Tab = "documents" | "references";

export default function CourseDetailPage() {
  const params = useParams();
  const courseId = params.id as string;

  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("documents");
  const [enriching, setEnriching] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  const [suggestions, setSuggestions] = useState<OrganizeSuggestion[]>([]);
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<number>>(new Set());

  function refreshCourse() {
    getCourse(courseId)
      .then(setCourse)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refreshCourse(); }, [courseId]);

  async function handleEnrich() {
    setEnriching(true);
    setError(null);
    try {
      const result = await enrichCourse(courseId);
      setError(null);
      alert(`Enriched ${result.nodes_enriched} nodes, skipped ${result.nodes_skipped}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enrichment failed");
    } finally {
      setEnriching(false);
    }
  }

  async function handleOrganize() {
    setOrganizing(true);
    setError(null);
    try {
      const result = await organizeCourse(courseId);
      setSuggestions(result.suggestions);
      setSelectedSuggestions(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Organization failed");
    } finally {
      setOrganizing(false);
    }
  }

  async function handleApplySuggestions() {
    if (selectedSuggestions.size === 0) return;
    try {
      const result = await applyOrganization(courseId, Array.from(selectedSuggestions));
      alert(`Applied ${result.applied} suggestions.`);
      setSuggestions([]);
      refreshCourse();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Apply failed");
    }
  }

  function toggleSuggestion(id: number) {
    setSelectedSuggestions((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (loading) return <p className="text-neutral-500">Loading...</p>;
  if (error && !course) return <p className="text-red-500">Error: {error}</p>;
  if (!course) return <p className="text-red-500">Course not found</p>;

  const hasGraph = course.ingestion_status === "graph_ready";

  return (
    <div>
      <div className="mb-6">
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-700">
          &larr; Back to courses
        </Link>
      </div>

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">{course.title}</h1>
          {course.description && (
            <p className="mt-1 text-neutral-500">{course.description}</p>
          )}
        </div>
        <StatusBadge status={course.ingestion_status} />
      </div>

      {error && <p className="mb-4 text-sm text-red-500">{error}</p>}

      <div className="mb-6 flex gap-3">
        {hasGraph && (
          <>
            <Link
              href={`/courses/${courseId}/graph`}
              className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
            >
              View Graph
            </Link>
            <button
              onClick={handleEnrich}
              disabled={enriching}
              className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              {enriching ? "Enriching..." : "Enrich Course"}
            </button>
            <button
              onClick={handleOrganize}
              disabled={organizing}
              className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              {organizing ? "Analyzing..." : "Organize Graph"}
            </button>
          </>
        )}
      </div>

      {suggestions.length > 0 && (
        <div className="mb-6 rounded-md border border-neutral-200 p-4 dark:border-neutral-800">
          <h3 className="mb-2 font-medium">Organization Suggestions</h3>
          <ul className="space-y-2">
            {suggestions.map((s) => (
              <li key={s.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedSuggestions.has(s.id)}
                  onChange={() => toggleSuggestion(s.id)}
                  className="mt-1"
                />
                <div>
                  <span className="mr-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">
                    {s.type}
                  </span>
                  <span className="font-medium">{s.node_titles.join(", ")}</span>
                  <p className="text-neutral-500">{s.reasoning}</p>
                </div>
              </li>
            ))}
          </ul>
          <button
            onClick={handleApplySuggestions}
            disabled={selectedSuggestions.size === 0}
            className="mt-3 rounded bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            Apply Selected ({selectedSuggestions.size})
          </button>
        </div>
      )}

      <div className="mt-6 rounded-md border border-neutral-200 p-4 text-sm dark:border-neutral-800">
        <h3 className="mb-2 font-medium">Details</h3>
        <dl className="grid grid-cols-2 gap-2 text-neutral-600 dark:text-neutral-400">
          <dt>Documents</dt>
          <dd>{course.document_count}</dd>
          <dt>Mastery Threshold</dt>
          <dd>{course.mastery_threshold}%</dd>
          <dt>Created</dt>
          <dd>{new Date(course.created_at).toLocaleString()}</dd>
        </dl>
      </div>

      <div className="mt-6">
        <div className="flex border-b border-neutral-200 dark:border-neutral-800">
          <button
            onClick={() => setTab("documents")}
            className={`px-4 py-2 text-sm ${tab === "documents" ? "border-b-2 border-neutral-900 font-medium dark:border-neutral-100" : "text-neutral-500"}`}
          >
            Documents
          </button>
          <button
            onClick={() => setTab("references")}
            className={`px-4 py-2 text-sm ${tab === "references" ? "border-b-2 border-neutral-900 font-medium dark:border-neutral-100" : "text-neutral-500"}`}
          >
            References
          </button>
        </div>
        <div className="mt-4">
          {tab === "documents" && (
            <DocumentList courseId={courseId} onExtracted={refreshCourse} />
          )}
          {tab === "references" && <ReferenceList courseId={courseId} />}
        </div>
      </div>
    </div>
  );
}
