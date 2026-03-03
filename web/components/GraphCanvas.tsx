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
  courseTitle: string;
  graphData: GraphData;
  onNodeSelect: (nodeId: string | null) => void;
  onGraphChange: () => void;
}

const FALLBACK_ROOT_ID = "__course_root__";

const nodeTypes = { topic: GraphNode };

const EDGE_STYLES: Record<string, { color: string; dash?: string; animated?: boolean }> = {
  dependency: { color: "#3b82f6", animated: true },
  association: { color: "#6b7280", dash: "5 5" },
  hierarchy: { color: "#22c55e" },
};

function toReactFlowElements(
  graphData: GraphData,
  courseTitle: string,
  onRename: (id: string, title: string) => void,
) {
  const hasRootNode = graphData.nodes.some((n) => n.depth === 0);

  const nodes: RFNode[] = [
    // Fallback synthetic root if no depth-0 node exists (old courses)
    ...(!hasRootNode
      ? [
          {
            id: FALLBACK_ROOT_ID,
            type: "topic" as const,
            position: { x: 0, y: 0 },
            data: { label: courseTitle, depth: 0, nodeType: "root" as const, onRename: () => {} },
          },
        ]
      : []),
    ...graphData.nodes.map((n) => ({
      id: n.id,
      type: "topic" as const,
      position: { x: 0, y: 0 },
      data: {
        label: n.title,
        depth: n.depth,
        nodeType: n.depth === 0 ? ("root" as const) : n.node_type,
        onRename: n.depth === 0 ? () => {} : onRename,
      },
    })),
  ];

  // Fallback edges from synthetic root to depth-1 nodes (old courses only)
  const fallbackEdges: RFEdge[] = !hasRootNode
    ? graphData.nodes
        .filter((n) => n.depth === 1)
        .map((n) => ({
          id: `${FALLBACK_ROOT_ID}-${n.id}`,
          source: FALLBACK_ROOT_ID,
          target: n.id,
          label: "",
          markerEnd: { type: MarkerType.ArrowClosed, color: "#8b5cf6" },
          style: { stroke: "#8b5cf6" },
          animated: false,
        }))
    : [];

  const edges: RFEdge[] = [
    ...fallbackEdges,
    ...graphData.edges.map((e) => {
      const style = EDGE_STYLES[e.edge_category] ?? EDGE_STYLES.association;
      return {
        id: `${e.parent_id}-${e.child_id}`,
        source: e.parent_id,
        target: e.child_id,
        label: e.edge_label,
        labelStyle: { fontSize: 10, fill: style.color },
        markerEnd: { type: MarkerType.ArrowClosed, color: style.color },
        style: {
          stroke: style.color,
          strokeDasharray: style.dash,
        },
        animated: style.animated ?? false,
      };
    }),
  ];

  return { nodes, edges };
}

export default function GraphCanvas({
  courseId,
  courseTitle,
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
    () => toReactFlowElements(graphData, courseTitle, handleRename),
    [graphData, courseTitle, handleRename],
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
      if (node.data.nodeType === "root" || node.id === FALLBACK_ROOT_ID) return;
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
