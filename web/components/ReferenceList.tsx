/** Reference list — CRUD for book/URL references attached to a course. */
"use client";

import { useEffect, useState } from "react";
import { getReferences, createReference, deleteReference } from "@/lib/api";
import type { ReferenceInfo } from "@/lib/types";

interface ReferenceListProps {
  courseId: string;
}

export default function ReferenceList({ courseId }: ReferenceListProps) {
  const [refs, setRefs] = useState<ReferenceInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [refType, setRefType] = useState<"book" | "url">("book");
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    getReferences(courseId)
      .then(setRefs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { refresh(); }, [courseId]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createReference(courseId, {
        ref_type: refType,
        title,
        author: author || null,
        isbn: null,
        url: refType === "url" ? url : null,
      });
      setTitle("");
      setAuthor("");
      setUrl("");
      setShowForm(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add reference");
    }
  }

  async function handleDelete(refId: string) {
    try {
      await deleteReference(courseId, refId);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete reference");
    }
  }

  if (loading) return <p className="text-sm text-neutral-500">Loading references...</p>;

  return (
    <div>
      {error && <p className="mb-2 text-sm text-red-500">{error}</p>}
      {refs.length === 0 && !showForm && (
        <p className="text-sm text-neutral-500">No references yet.</p>
      )}
      <ul className="space-y-2">
        {refs.map((r) => (
          <li
            key={r.id}
            className="flex items-center justify-between rounded-md border border-neutral-200 p-3 text-sm dark:border-neutral-800"
          >
            <div>
              <span className="mr-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">
                {r.ref_type}
              </span>
              <span className="font-medium">{r.title}</span>
              {r.author && <span className="ml-1 text-neutral-400">by {r.author}</span>}
              {r.url && (
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="ml-2 text-blue-500 hover:underline">
                  link
                </a>
              )}
            </div>
            <button
              onClick={() => handleDelete(r.id)}
              className="text-xs text-red-400 hover:text-red-600"
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      {showForm ? (
        <form onSubmit={handleAdd} className="mt-3 space-y-2 rounded border border-neutral-200 p-3 text-sm dark:border-neutral-800">
          <select
            value={refType}
            onChange={(e) => setRefType(e.target.value as "book" | "url")}
            className="w-full rounded border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          >
            <option value="book">Book</option>
            <option value="url">URL</option>
          </select>
          <input
            type="text"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="w-full rounded border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
          <input
            type="text"
            placeholder="Author (optional)"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            className="w-full rounded border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
          {refType === "url" && (
            <input
              type="url"
              placeholder="URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="w-full rounded border border-neutral-300 px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            />
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              className="rounded bg-neutral-900 px-3 py-1 text-xs text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="text-xs text-neutral-500 hover:text-neutral-700"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button
          onClick={() => setShowForm(true)}
          className="mt-3 text-sm text-neutral-500 hover:text-neutral-700"
        >
          + Add Reference
        </button>
      )}
    </div>
  );
}
