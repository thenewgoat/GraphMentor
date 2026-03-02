import Link from "next/link";
import { Course } from "@/lib/types";
import StatusBadge from "./StatusBadge";

export default function CourseCard({ course }: { course: Course }) {
  return (
    <Link
      href={`/courses/${course.id}`}
      className="block rounded-lg border border-neutral-200 p-4 transition-colors hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600"
    >
      <div className="flex items-start justify-between">
        <h2 className="text-lg font-medium">{course.title}</h2>
        <StatusBadge status={course.ingestion_status} />
      </div>
      {course.description && (
        <p className="mt-1 text-sm text-neutral-500">{course.description}</p>
      )}
      <p className="mt-2 text-xs text-neutral-400">
        {new Date(course.created_at).toLocaleDateString()}
      </p>
    </Link>
  );
}
