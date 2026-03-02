/** PDF upload form — course selector, title input, file picker, submit. */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadPdf, getCourses } from "@/lib/api";
import type { Course } from "@/lib/types";

export default function UploadForm() {
  const router = useRouter();
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string>("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCourses().then(setCourses).catch(() => {});
  }, []);

  const isNewCourse = selectedCourseId === "";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !title.trim()) return;

    setUploading(true);
    setError(null);

    try {
      const result = await uploadPdf(
        file,
        title.trim(),
        isNewCourse ? undefined : selectedCourseId,
      );
      router.push(`/courses/${result.course_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-md space-y-4">
      <div>
        <label htmlFor="course" className="block text-sm font-medium">
          Course
        </label>
        <select
          id="course"
          value={selectedCourseId}
          onChange={(e) => setSelectedCourseId(e.target.value)}
          className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        >
          <option value="">New Course</option>
          {courses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="title" className="block text-sm font-medium">
          {isNewCourse ? "Course Title" : "Document Title"}
        </label>
        <input
          id="title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={isNewCourse ? "e.g. Data Structures" : file?.name?.replace(".pdf", "") || "e.g. Lecture 2"}
          required
          className="mt-1 w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
      </div>

      <div>
        <label htmlFor="file" className="block text-sm font-medium">
          PDF File
        </label>
        <input
          id="file"
          type="file"
          accept=".pdf"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          required
          className="mt-1 w-full text-sm"
        />
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={uploading || !file || !title.trim()}
        className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
      >
        {uploading ? "Uploading..." : "Upload"}
      </button>
    </form>
  );
}
