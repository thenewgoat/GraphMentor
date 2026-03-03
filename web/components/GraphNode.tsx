/** Custom React Flow node — inline rename on double-click, depth label. */
import { memo, useState, useCallback } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";

type GraphNodeData = {
  label: string;
  depth: number;
  nodeType: "concept" | "group" | "root";
  onRename: (id: string, title: string) => void;
};

export type TopicNode = Node<GraphNodeData, "topic">;

function GraphNodeInner({ id, data }: NodeProps<TopicNode>) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(data.label);

  const handleDoubleClick = useCallback(() => {
    setEditing(true);
  }, []);

  const handleBlur = useCallback(() => {
    setEditing(false);
    if (title.trim() && title !== data.label) {
      data.onRename(id, title.trim());
    } else {
      setTitle(data.label);
    }
  }, [id, title, data]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        (e.target as HTMLInputElement).blur();
      }
      if (e.key === "Escape") {
        setTitle(data.label);
        setEditing(false);
      }
    },
    [data.label],
  );

  return (
    <div className={`rounded-md px-3 py-2 shadow-sm ${
  data.nodeType === "root"
    ? "border-2 border-purple-400 bg-purple-50 dark:border-purple-600 dark:bg-purple-950"
    : data.nodeType === "group"
    ? "border-2 border-dashed border-blue-300 bg-blue-50 dark:border-blue-700 dark:bg-blue-950"
    : "border border-neutral-300 bg-white dark:border-neutral-600 dark:bg-neutral-800"
}`}>
      {data.nodeType !== "root" && (
        <Handle type="target" position={Position.Top} className="!bg-neutral-400" />
      )}

      {editing ? (
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          className="w-full border-none bg-transparent text-sm font-medium outline-none"
        />
      ) : (
        <div onDoubleClick={handleDoubleClick} className="cursor-text text-sm font-medium">
          {data.label}
        </div>
      )}

      {data.nodeType !== "root" && (
        <div className="mt-0.5 text-xs text-neutral-400">
          {data.nodeType === "group" ? "group" : `depth ${data.depth}`}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-neutral-400" />
    </div>
  );
}

export default memo(GraphNodeInner);
