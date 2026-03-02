/** Document list — shows uploaded docs with extract and delete buttons. */
"use client";

import { useEffect, useState } from "react";
import { getDocuments, extractTopics, deleteDocument } from "@/lib/api";
import type { DocumentInfo, IngestionStatus } from "@/lib/types";
import StatusBadge from "./StatusBadge";
import ConfirmDialog from "./ConfirmDialog";

interface DocumentListProps {
  courseId: string;
  onExtracted: () => void;
}

export default function DocumentList({ courseId, onExtracted }: DocumentListProps) {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [extractingId, setExtractingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    getDocuments(courseId)
      .then(setDocs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, [courseId]);

  async function handleExtract(docId: string) {
    setExtractingId(docId);
    setError(null);
    try {
      await extractTopics(courseId, docId);
      onExtracted();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extraction failed");
    } finally {
      setExtractingId(null);
    }
  }

  async function handleDelete(docId: string) {
    setConfirmDeleteId(null);
    setDeletingId(docId);
    setError(null);
    try {
      await deleteDocument(courseId, docId);
      onExtracted();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) return <p className="text-sm text-neutral-500">Loading documents...</p>;

  return (
    <div>
      {error && <p className="mb-2 text-sm text-red-500">{error}</p>}
      {docs.length === 0 ? (
        <p className="text-sm text-neutral-500">No documents uploaded yet.</p>
      ) : (
        <ul className="space-y-2">
          {docs.map((d) => (
            <li
              key={d.id}
              className="flex items-center justify-between rounded-md border border-neutral-200 p-3 text-sm dark:border-neutral-800"
            >
              <div>
                <span className="font-medium">{d.title}</span>
                <span className="ml-2 text-neutral-400">({d.filename})</span>
                {d.page_count != null && (
                  <span className="ml-2 text-neutral-400">{d.page_count} pages</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={d.ingestion_status as IngestionStatus} />
                {d.ingestion_status === "complete" && (
                  <button
                    onClick={() => handleExtract(d.id)}
                    disabled={extractingId === d.id}
                    className="rounded bg-neutral-900 px-3 py-1 text-xs text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
                  >
                    {extractingId === d.id ? "Extracting..." : "Extract"}
                  </button>
                )}
                <button
                  onClick={() => setConfirmDeleteId(d.id)}
                  disabled={deletingId === d.id}
                  className="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
                >
                  {deletingId === d.id ? "Removing..." : "Remove"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {confirmDeleteId && (
        <ConfirmDialog
          message="Remove this document? Its pages, embeddings, and any orphaned nodes will be deleted."
          onConfirm={() => handleDelete(confirmDeleteId)}
          onCancel={() => setConfirmDeleteId(null)}
        />
      )}
    </div>
  );
}
