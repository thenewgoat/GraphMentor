/** Colored pill badge showing ingestion status. */
import { IngestionStatus } from "@/lib/types";

const STATUS_COLORS: Record<IngestionStatus, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  complete: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  graph_ready: "bg-purple-100 text-purple-800",
};

export default function StatusBadge({ status }: { status: IngestionStatus }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status]}`}>
      {status.replace("_", " ")}
    </span>
  );
}
