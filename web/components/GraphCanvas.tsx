/** React Flow canvas — renders DAG with node CRUD and edge connections. */
"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node as RFNode,
  Edge as RFEdge,
  Connection,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import GraphNode from "./GraphNode";
import { GraphData } from "@/lib/api";
import { applyDagreLayout } from "@/lib/layout";

import * as api from "@/lib/api";

interface GraphCanvasProps {
  courseId: string;
  graphData: GraphData;
  onNodeSelect: (nodeId: string | null) => void;
  onGraphChange: () => void;
}

const nodeTypes = { topic: GraphNode };

function toReactFlowData(
  graphData: GraphData,
  onRename: (id: string, title: string) => void,
) {
  const nodes: RFNode[] = graphData.nodes.map((n) => ({
    id: n.id,
    type: "topic" as const,
    position: { x: 0, y: 0 },
    data: { label: n.title, depth: n.depth, onRename },
  }));

  const edges: RFEdge[] = graphData.edges.map((e) => ({
    id: `${e.parent_id}-${e.child_id}`,
    source: e.parent_id,
    target: e.child_id,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: e.edge_type === "related" ? { strokeDasharray: "5 5" } : undefined,
    animated: e.edge_type === "prerequisite",
  }));

  return applyDagreLayout(nodes, edges);
}

export default function GraphCanvas({
  courseId,
  graphData,
  onNodeSelect,
  onGraphChange,
}: GraphCanvasProps) {
  const handleRename = useCallback(
    async (nodeId: string, title: string) => {
      await api.updateNode(courseId, nodeId, { title });
      onGraphChange();
    },
    [courseId, onGraphChange],
  );

  const initial = useMemo(
    () => toReactFlowData(graphData, handleRename),
    [graphData, handleRename],
  );

  const [nodes, , onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  const onConnect = useCallback(
    async (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      try {
        await api.createEdge(courseId, connection.source, connection.target);
        setEdges((eds) =>
          addEdge(
            {
              ...connection,
              markerEnd: { type: MarkerType.ArrowClosed },
              animated: true,
            },
            eds,
          ),
        );
        onGraphChange();
      } catch (err) {
        alert(err instanceof Error ? err.message : "Failed to create edge");
      }
    },
    [courseId, setEdges, onGraphChange],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: RFNode) => {
      onNodeSelect(node.id);
    },
    [onNodeSelect],
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect(null);
  }, [onNodeSelect]);

  const onEdgesDelete = useCallback(
    async (deletedEdges: RFEdge[]) => {
      for (const edge of deletedEdges) {
        await api.deleteEdge(courseId, edge.source, edge.target);
      }
      onGraphChange();
    },
    [courseId, onGraphChange],
  );

  const handleAddNode = useCallback(async () => {
    try {
      await api.createNode(courseId, "New Topic");
      onGraphChange();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create node");
    }
  }, [courseId, onGraphChange]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-neutral-200 px-3 py-2 dark:border-neutral-800">
        <button
          onClick={handleAddNode}
          className="rounded bg-neutral-900 px-3 py-1 text-xs text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900"
        >
          + Add Node
        </button>
      </div>
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onEdgesDelete={onEdgesDelete}
          fitView
          deleteKeyCode="Delete"
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
    </div>
  );
}
