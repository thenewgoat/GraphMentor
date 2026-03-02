/** ELK-based hierarchical auto-layout for React Flow graphs. */
import ELK, { ElkNode, ElkExtendedEdge } from "elkjs/lib/elk.bundled.js";
import { Node as RFNode, Edge as RFEdge } from "@xyflow/react";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 50;

const elk = new ELK();

export async function applyElkLayout(
  nodes: RFNode[],
  edges: RFEdge[],
): Promise<{ nodes: RFNode[]; edges: RFEdge[] }> {
  const elkNodes: ElkNode[] = nodes.map((n) => ({
    id: n.id,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
  }));

  const elkEdges: ElkExtendedEdge[] = edges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  const graph = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      "elk.spacing.nodeNode": "40",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: elkNodes,
    edges: elkEdges,
  });

  const posMap = new Map<string, { x: number; y: number }>();
  for (const child of graph.children ?? []) {
    posMap.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }

  const layoutNodes = nodes.map((n) => ({
    ...n,
    position: posMap.get(n.id) ?? { x: 0, y: 0 },
  }));

  return { nodes: layoutNodes, edges };
}
