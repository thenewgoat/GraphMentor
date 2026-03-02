"use client";

import { useState, useCallback } from "react";
import { GraphNode } from "@/lib/api";
import { NodeEdge } from "@/lib/types";
import * as api from "@/lib/api";
import ConfirmDialog from "./ConfirmDialog";

interface NodeSidebarProps {
  courseId: string;
  node: GraphNode;
  allNodes: GraphNode[];
  allEdges: NodeEdge[];
  onClose: () => void;
  onGraphChange: () => void;
}

export default function NodeSidebar({
  courseId,
  node,
  allNodes,
  allEdges,
  onClose,
  onGraphChange,
}: NodeSidebarProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  const prerequisites = allEdges
    .filter((e) => e.child_id === node.id)
    .map((e) => allNodes.find((n) => n.id === e.parent_id))
    .filter(Boolean) as GraphNode[];

  const dependents = allEdges
    .filter((e) => e.parent_id === node.id)
    .map((e) => allNodes.find((n) => n.id === e.child_id))
    .filter(Boolean) as GraphNode[];

  const handleDelete = useCallback(async () => {
    await api.deleteNode(courseId, node.id);
    setConfirmDelete(false);
    onClose();
    onGraphChange();
  }, [courseId, node.id, onClose, onGraphChange]);

  return (
    <div className="w-1/4 overflow-y-auto border-l border-neutral-200 p-4 dark:border-neutral-800">
      <div className="mb-4 flex items-start justify-between">
        <h3 className="text-lg font-semibold">{node.title}</h3>
        <button onClick={onClose} className="text-neutral-400 hover:text-neutral-600">
          &times;
        </button>
      </div>

      <dl className="mb-4 space-y-2 text-sm">
        <dt className="font-medium text-neutral-500">Depth</dt>
        <dd>{node.depth}</dd>
      </dl>

      {prerequisites.length > 0 && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-neutral-500">Prerequisites</h4>
          <ul className="space-y-1">
            {prerequisites.map((p) => (
              <li key={p.id} className="text-sm">
                {p.title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dependents.length > 0 && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-neutral-500">Dependents</h4>
          <ul className="space-y-1">
            {dependents.map((d) => (
              <li key={d.id} className="text-sm">
                {d.title}
              </li>
            ))}
          </ul>
        </div>
      )}

      {node.sentences.length > 0 && (
        <div className="mb-4">
          <h4 className="mb-1 text-sm font-medium text-neutral-500">
            Source Sentences ({node.sentences.length})
          </h4>
          <ul className="max-h-60 space-y-2 overflow-y-auto">
            {node.sentences.map((s) => (
              <li key={s.id} className="rounded bg-neutral-50 p-2 text-xs dark:bg-neutral-900">
                <span className="text-neutral-400">p.{s.page}</span> {s.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        onClick={() => setConfirmDelete(true)}
        className="w-full rounded bg-red-50 px-3 py-1.5 text-sm text-red-600 hover:bg-red-100 dark:bg-red-900/20 dark:text-red-400"
      >
        Delete Node
      </button>

      {confirmDelete && (
        <ConfirmDialog
          message={`Delete "${node.title}" and all its edges?`}
          onConfirm={handleDelete}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}
