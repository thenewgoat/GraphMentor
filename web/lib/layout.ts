/** ELK-based hierarchical auto-layout for React Flow graphs. */
import ELK, { ElkNode, ElkExtendedEdge } from "elkjs/lib/elk.bundled.js";
import { Node as RFNode, Edge as RFEdge } from "@xyflow/react";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 50;
const ROOT_WIDTH = 220;
const ROOT_HEIGHT = 44;

const elk = new ELK();

export async function applyElkLayout(
  nodes: RFNode[],
  edges: RFEdge[],
): Promise<{ nodes: RFNode[]; edges: RFEdge[] }> {
  const elkNodes: ElkNode[] = nodes.map((n) => {
    const isRoot = n.data?.nodeType === "root";
    return {
      id: n.id,
      width: isRoot ? ROOT_WIDTH : NODE_WIDTH,
      height: isRoot ? ROOT_HEIGHT : NODE_HEIGHT,
    };
  });

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
      "elk.layered.spacing.nodeNodeBetweenLayers": "100",
      "elk.spacing.nodeNode": "50",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
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
