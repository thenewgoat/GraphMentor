/** React Flow canvas — renders DAG with node CRUD and edge connections. */
"use client";

import { useCallback, useEffect, useMemo } from "react";
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
import { applyElkLayout } from "@/lib/layout";

import * as api from "@/lib/api";

interface GraphCanvasProps {
  courseId: string;
  graphData: GraphData;
  onNodeSelect: (nodeId: string | null) => void;
  onGraphChange: () => void;
}

const nodeTypes = { topic: GraphNode };

const EDGE_STYLES: Record<string, { color: string; dash?: string; animated?: boolean }> = {
  prerequisite: { color: "#3b82f6", animated: true },
  subtopic: { color: "#6b7280" },
  method_of: { color: "#22c55e", dash: "5 5" },
  motivation: { color: "#f97316", dash: "5 5" },
  application: { color: "#a855f7", dash: "8 4" },
  related: { color: "#6b7280", dash: "3 3" },
};

function toReactFlowElements(
  graphData: GraphData,
  onRename: (id: string, title: string) => void,
) {
  const nodes: RFNode[] = graphData.nodes.map((n) => ({
    id: n.id,
    type: "topic" as const,
    position: { x: 0, y: 0 },
    data: { label: n.title, depth: n.depth, onRename },
  }));

  const edges: RFEdge[] = graphData.edges.map((e) => {
    const style = EDGE_STYLES[e.edge_type] ?? EDGE_STYLES.related;
    return {
      id: `${e.parent_id}-${e.child_id}`,
      source: e.parent_id,
      target: e.child_id,
      label: e.edge_type.replace("_", " "),
      labelStyle: { fontSize: 10, fill: style.color },
      markerEnd: { type: MarkerType.ArrowClosed, color: style.color },
      style: {
        stroke: style.color,
        strokeDasharray: style.dash,
      },
      animated: style.animated ?? false,
    };
  });

  return { nodes, edges };
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

  const elements = useMemo(
    () => toReactFlowElements(graphData, handleRename),
    [graphData, handleRename],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(elements.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(elements.edges);

  // Run async ELK layout when graph data changes
  useEffect(() => {
    applyElkLayout(elements.nodes, elements.edges).then(({ nodes: laid, edges: laidEdges }) => {
      setNodes(laid);
      setEdges(laidEdges);
    });
  }, [elements, setNodes, setEdges]);

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
