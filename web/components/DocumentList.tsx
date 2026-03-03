/** Document list — batch upload, extract all, and per-doc management. */
"use client";

import { useEffect, useState } from "react";
import { getDocuments, deleteDocument, uploadPdf } from "@/lib/api";
import { useExtraction } from "@/lib/extraction-context";
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
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);

  const extraction = useExtraction();
  const extractingAll = extraction.isExtractingAll(courseId);
  const anyExtracting = extractingAll || docs.some((d) => extraction.isExtracting(d.id));

  function refresh() {
    getDocuments(courseId)
      .then(setDocs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, [courseId]);

  function handleExtract(docId: string) {
    setError(null);
    extraction.extractOne(courseId, docId, () => {
      onExtracted();
      refresh();
    });
  }

  function handleExtractAll() {
    const unextracted = docs.filter((d) => d.ingestion_status === "complete");
    if (unextracted.length === 0) return;
    setError(null);
    extraction.extractAll(
      courseId,
      unextracted.map((d) => ({ id: d.id, title: d.title })),
      () => {
        onExtracted();
        refresh();
      },
    );
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

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (uploadFiles.length === 0) return;
    setUploading(true);
    setError(null);

    for (let i = 0; i < uploadFiles.length; i++) {
      const file = uploadFiles[i];
      setUploadProgress(`Uploading ${i + 1}/${uploadFiles.length}: ${file.name}`);
      try {
        await uploadPdf(file, file.name, courseId);
      } catch (err) {
        setError(err instanceof Error ? err.message : `Upload failed: ${file.name}`);
        setUploading(false);
        setUploadProgress(null);
        refresh();
        return;
      }
    }

    setUploadFiles([]);
    setShowUpload(false);
    setUploading(false);
    setUploadProgress(null);
    onExtracted();
    refresh();
  }

  if (loading) return <p className="text-sm text-neutral-500">Loading documents...</p>;

  const displayError = error || extraction.error;
  const hasReadyDocs = docs.some((d) => d.ingestion_status === "complete");

  return (
    <div>
      {displayError && <p className="mb-2 text-sm text-red-500">{displayError}</p>}
      {hasReadyDocs && docs.length > 0 && (
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs text-neutral-500">
            {docs.filter((d) => d.ingestion_status === "complete").length} document(s) ready
          </p>
          <button
            onClick={handleExtractAll}
            disabled={anyExtracting}
            className="rounded bg-neutral-900 px-3 py-1.5 text-xs text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
          >
            {extractingAll ? "Generating..." : "Generate Graph"}
          </button>
        </div>
      )}
      {(extraction.progress || uploadProgress) && (
        <p className="mb-2 text-xs text-neutral-500">{extraction.progress || uploadProgress}</p>
      )}
      {docs.length === 0 ? (
        <p className="text-sm text-neutral-500">No documents uploaded yet.</p>
      ) : (
        <ul className="space-y-2">
          {docs.map((d) => {
            const isExtracting = extraction.isExtracting(d.id);
            return (
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
                  <button
                    onClick={() => setConfirmDeleteId(d.id)}
                    disabled={deletingId === d.id}
                    className="text-xs text-red-400 hover:text-red-600 disabled:opacity-50"
                  >
                    {deletingId === d.id ? "Removing..." : "Remove"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {confirmDeleteId && (
        <ConfirmDialog
          message="Remove this document? Its pages, embeddings, and any orphaned nodes will be deleted."
          onConfirm={() => handleDelete(confirmDeleteId)}
          onCancel={() => setConfirmDeleteId(null)}
        />
      )}
      {showUpload ? (
        <form onSubmit={handleUpload} className="mt-3 space-y-2 rounded border border-neutral-200 p-3 text-sm dark:border-neutral-800">
          <input
            type="file"
            accept=".pdf"
            multiple
            onChange={(e) => setUploadFiles(Array.from(e.target.files || []))}
            required
            className="w-full text-sm"
          />
          {uploadFiles.length > 1 && (
            <p className="text-xs text-neutral-500">{uploadFiles.length} files selected</p>
          )}
          {uploadProgress && (
            <p className="text-xs text-neutral-500">{uploadProgress}</p>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={uploading || uploadFiles.length === 0}
              className="rounded bg-neutral-900 px-3 py-1 text-xs text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
            >
              {uploading ? "Uploading..." : `Upload${uploadFiles.length > 1 ? ` (${uploadFiles.length})` : ""}`}
            </button>
            <button
              type="button"
              onClick={() => { setShowUpload(false); setUploadFiles([]); }}
              className="text-xs text-neutral-500 hover:text-neutral-700"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button
          onClick={() => setShowUpload(true)}
          className="mt-3 text-sm text-neutral-500 hover:text-neutral-700"
        >
          + Add Documents
        </button>
      )}
    </div>
  );
}
