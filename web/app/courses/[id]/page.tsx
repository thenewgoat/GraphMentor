"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Course } from "@/lib/types";
import { getCourse, extractTopics } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function CourseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const courseId = params.id as string;

  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);

  useEffect(() => {
    getCourse(courseId)
      .then(setCourse)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [courseId]);

  async function handleExtract() {
    setExtracting(true);
    setError(null);
    try {
      await extractTopics(courseId);
      const updated = await getCourse(courseId);
      setCourse(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }

  if (loading) return <p className="text-neutral-500">Loading...</p>;
  if (error && !course) return <p className="text-red-500">Error: {error}</p>;
  if (!course) return <p className="text-red-500">Course not found</p>;

  const canExtract = course.ingestion_status === "complete";
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

      <div className="flex gap-3">
        {canExtract && (
          <button
            onClick={handleExtract}
            disabled={extracting}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
          >
            {extracting ? "Extracting..." : "Extract Topics"}
          </button>
        )}

        {hasGraph && (
          <Link
            href={`/courses/${courseId}/graph`}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
          >
            View Graph
          </Link>
        )}
      </div>

      <div className="mt-8 rounded-md border border-neutral-200 p-4 text-sm dark:border-neutral-800">
        <h3 className="mb-2 font-medium">Details</h3>
        <dl className="grid grid-cols-2 gap-2 text-neutral-600 dark:text-neutral-400">
          <dt>PDF Path</dt>
          <dd className="truncate">{course.source_pdf_path}</dd>
          <dt>Mastery Threshold</dt>
          <dd>{course.mastery_threshold}%</dd>
          <dt>Created</dt>
          <dd>{new Date(course.created_at).toLocaleString()}</dd>
        </dl>
      </div>
    </div>
  );
}
