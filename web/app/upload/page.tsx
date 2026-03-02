/** New Course page — course creation form with back navigation. */
import UploadForm from "@/components/UploadForm";
import Link from "next/link";

export default function UploadPage() {
  return (
    <div>
      <div className="mb-6">
        <Link href="/" className="text-sm text-neutral-500 hover:text-neutral-700">
          &larr; Back to courses
        </Link>
        <h1 className="mt-2 text-2xl font-bold">New Course</h1>
      </div>
      <UploadForm />
    </div>
  );
}
