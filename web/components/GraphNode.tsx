import { memo, useState, useCallback } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";

type GraphNodeData = {
  label: string;
  depth: number;
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
    <div className="rounded-md border border-neutral-300 bg-white px-3 py-2 shadow-sm dark:border-neutral-600 dark:bg-neutral-800">
      <Handle type="target" position={Position.Top} className="!bg-neutral-400" />

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

      <div className="mt-0.5 text-xs text-neutral-400">depth {data.depth}</div>

      <Handle type="source" position={Position.Bottom} className="!bg-neutral-400" />
    </div>
  );
}

export default memo(GraphNodeInner);
