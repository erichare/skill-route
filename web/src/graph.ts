import type { Edge, Node } from "@xyflow/react";
import type { AtlasEdgeRecord, AtlasNodeRecord, AtlasPayload } from "./types";

export interface AtlasFilters {
  search: string;
  domains: string[];
  relationshipTypes: string[];
  orphansOnly: boolean;
  conflictsOnly: boolean;
}

export interface SkillNodeData extends Record<string, unknown> {
  record: AtlasNodeRecord;
  selected: boolean;
  routeRank?: number;
}

export interface DomainNodeData extends Record<string, unknown> {
  id: string;
  name: string;
  count: number;
  color: string;
  selected: boolean;
}

export interface LayoutResult {
  nodes: Array<Node<SkillNodeData | DomainNodeData>>;
  edges: Edge[];
  visibleSkillIds: Set<string>;
}

const CANVAS_WIDTH = 1140;
const CANVAS_HEIGHT = 760;
const CENTER_X = CANVAS_WIDTH / 2;
const CENTER_Y = CANVAS_HEIGHT / 2;

export function defaultFilters(atlas: AtlasPayload): AtlasFilters {
  return {
    search: "",
    domains: atlas.domains.map((domain) => domain.id),
    relationshipTypes: atlas.relationshipTypes.map((relationship) => relationship.type),
    orphansOnly: false,
    conflictsOnly: false
  };
}

export function layoutAtlasGraph(
  atlas: AtlasPayload,
  filters: AtlasFilters,
  selectedId: string | null,
  routeOrder: string[] = []
): LayoutResult {
  const visibleSkillIds = filteredSkillIds(atlas, filters);
  const routeRanks = new Map(routeOrder.map((skillId, index) => [skillId, index + 1]));
  const routePairs = new Set(
    routeOrder.slice(0, -1).map((skillId, index) => `${skillId}:${routeOrder[index + 1]}`)
  );
  const nodes: Array<Node<SkillNodeData | DomainNodeData>> = [];
  const domainCenters = domainCenterMap(atlas.domains.map((domain) => domain.id));

  for (const domain of atlas.domains) {
    if (!filters.domains.includes(domain.id)) {
      continue;
    }
    const center = domainCenters.get(domain.id) ?? { x: CENTER_X, y: CENTER_Y };
    const skills = atlas.nodes
      .filter((node) => node.domain === domain.id && visibleSkillIds.has(node.id))
      .sort((a, b) => a.name.localeCompare(b.name));
    nodes.push({
      id: `domain:${domain.id}`,
      type: "domain",
      position: { x: center.x - 72, y: center.y - clusterRadius(skills.length) - 54 },
      selectable: false,
      draggable: false,
      data: {
        id: domain.id,
        name: domain.name,
        count: skills.length,
        color: domain.color,
        selected: selectedId === `domain:${domain.id}`
      }
    });
    skills.forEach((skill, index) => {
      const position = skillPosition(center, index, skills.length);
      nodes.push({
        id: skill.id,
        type: "skill",
        position,
        data: {
          record: skill,
          selected: selectedId === skill.id,
          routeRank: routeRanks.get(skill.id)
        }
      });
    });
  }

  const edges = atlas.edges
    .filter((edge) => visibleSkillIds.has(edge.source) && visibleSkillIds.has(edge.target))
    .filter((edge) => filters.relationshipTypes.includes(edge.type))
    .map((edge) => graphEdge(edge, routePairs.has(`${edge.source}:${edge.target}`)));

  return { nodes, edges, visibleSkillIds };
}

export function filteredSkillIds(atlas: AtlasPayload, filters: AtlasFilters): Set<string> {
  const search = filters.search.trim().toLowerCase();
  const conflictSkillIds = new Set(
    atlas.edges
      .filter((edge) => edge.type === "conflicts")
      .flatMap((edge) => [edge.source, edge.target])
  );
  const connectedSkillIds = new Set(atlas.edges.flatMap((edge) => [edge.source, edge.target]));
  return new Set(
    atlas.nodes
      .filter((node) => filters.domains.includes(node.domain))
      .filter((node) => !search || matchesSearch(node, search))
      .filter((node) => !filters.orphansOnly || !connectedSkillIds.has(node.id))
      .filter(
        (node) =>
          !filters.conflictsOnly ||
          conflictSkillIds.has(node.id) ||
          node.relationshipSummary.conflicts > 0
      )
      .map((node) => node.id)
  );
}

export function domainCenterMap(domainIds: string[]): Map<string, { x: number; y: number }> {
  const centers = new Map<string, { x: number; y: number }>();
  const radiusX = 365;
  const radiusY = 265;
  domainIds.forEach((domain, index) => {
    const angle = -Math.PI / 2 + (index / Math.max(domainIds.length, 1)) * Math.PI * 2;
    const emphasis = index === 0 ? 0.24 : 1;
    centers.set(domain, {
      x: CENTER_X + Math.cos(angle) * radiusX * emphasis,
      y: CENTER_Y + Math.sin(angle) * radiusY * emphasis
    });
  });
  return centers;
}

function skillPosition(center: { x: number; y: number }, index: number, count: number): { x: number; y: number } {
  if (count === 1) {
    return { x: center.x, y: center.y };
  }
  const ring = Math.floor(index / 18);
  const ringIndex = index % 18;
  const ringCount = Math.min(18, count - ring * 18);
  const radius = clusterRadius(Math.min(count, 18)) + ring * 34;
  const angle = -Math.PI / 2 + (ringIndex / ringCount) * Math.PI * 2 + ring * 0.28;
  return {
    x: center.x + Math.cos(angle) * radius,
    y: center.y + Math.sin(angle) * radius
  };
}

function clusterRadius(count: number): number {
  return Math.max(54, Math.min(132, 22 + Math.sqrt(Math.max(count, 1)) * 16));
}

function graphEdge(edge: AtlasEdgeRecord, selectedPath: boolean): Edge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: selectedPath,
    label: selectedPath ? edge.label : undefined,
    style: {
      stroke: edge.color,
      strokeWidth: selectedPath ? 2.6 : 1.2,
      opacity: selectedPath ? 0.95 : 0.22
    },
    data: {
      relationshipType: edge.type
    }
  };
}

function matchesSearch(node: AtlasNodeRecord, search: string): boolean {
  const facetText = Object.values(node.facets).flat().join(" ");
  return [node.name, node.description, node.domain, node.tags.join(" "), facetText]
    .join(" ")
    .toLowerCase()
    .includes(search);
}
