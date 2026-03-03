/** Graph editor page — interactive DAG canvas with node sidebar. */
"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ReactFlowProvider } from "@xyflow/react";

import GraphCanvas from "@/components/GraphCanvas";
import NodeSidebar from "@/components/NodeSidebar";
import { GraphData, GraphNode, Course, getGraph, getCourse } from "@/lib/api";

export default function GraphEditorPage() {
  const params = useParams();
  const courseId = params.id as string;

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const fetchGraph = useCallback(() => {
    setLoading(true);
    Promise.all([getGraph(courseId), getCourse(courseId)])
      .then(([g, c]) => { setGraphData(g); setCourse(c); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [courseId]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const selectedNode: GraphNode | null =
    graphData?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  if (loading) return <p className="text-neutral-500">Loading graph...</p>;
  if (error) return <p className="text-red-500">Error: {error}</p>;
  if (!graphData) return null;

  return (
    <div className="flex h-[calc(100vh-theme(spacing.16))] flex-col">
      <div className="mb-2">
        <Link
          href={`/courses/${courseId}`}
          className="text-sm text-neutral-500 hover:text-neutral-700"
        >
          &larr; Back to course
        </Link>
      </div>

      <div className="flex flex-1 overflow-hidden rounded-lg border border-neutral-200 dark:border-neutral-800">
        <div className={selectedNode ? "w-3/4" : "w-full"}>
          <ReactFlowProvider>
            <GraphCanvas
              courseId={courseId}
              courseTitle={course?.title ?? "Course"}
              graphData={graphData}
              onNodeSelect={setSelectedNodeId}
              onGraphChange={fetchGraph}
            />
          </ReactFlowProvider>
        </div>

        {selectedNode && (
          <NodeSidebar
            courseId={courseId}
            node={selectedNode}
            allNodes={graphData.nodes}
            allEdges={graphData.edges}
            onClose={() => setSelectedNodeId(null)}
            onGraphChange={fetchGraph}
          />
        )}
      </div>
    </div>
  );
}
