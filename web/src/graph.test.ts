import { describe, expect, it } from "vitest";
import { defaultFilters, filteredSkillIds, layoutAtlasGraph } from "./graph";
import type { AtlasPayload } from "./types";

const atlas: AtlasPayload = {
  catalog: {
    path: "/tmp/catalog.db",
    skillCount: 3,
    domainCount: 2,
    relationshipCount: 2,
    unresolvedRelationshipCount: 0,
    orphanCount: 1,
    conflictCount: 1,
    backendRefCounts: {},
    fingerprint: "abc"
  },
  domains: [
    { id: "routing", name: "Routing", count: 2, color: "#fb923c" },
    { id: "testing", name: "Testing", count: 1, color: "#a3e635" }
  ],
  relationshipTypes: [
    { type: "requires", count: 1, color: "#60a5fa" },
    { type: "conflicts", count: 1, color: "#f87171" }
  ],
  nodes: [
    {
      id: "router",
      name: "Router",
      description: "Route user requests to skills.",
      domain: "routing",
      color: "#fb923c",
      tags: ["routing"],
      facets: { domain: ["routing"] },
      skillPath: "/skills/router/SKILL.md",
      bundlePath: "/skills/router",
      rootPath: "/skills",
      contentHash: "1",
      excerptCount: 1,
      referenceCount: 1,
      relationshipSummary: { incoming: 0, outgoing: 1, unresolved: 0, conflicts: 0 },
      backendRefs: []
    },
    {
      id: "planner",
      name: "Planner",
      description: "Plan agent workflows.",
      domain: "routing",
      color: "#fb923c",
      tags: ["routing"],
      facets: { domain: ["routing"] },
      skillPath: "/skills/planner/SKILL.md",
      bundlePath: "/skills/planner",
      rootPath: "/skills",
      contentHash: "2",
      excerptCount: 1,
      referenceCount: 1,
      relationshipSummary: { incoming: 1, outgoing: 0, unresolved: 0, conflicts: 0 },
      backendRefs: []
    },
    {
      id: "pytest",
      name: "Pytest",
      description: "Write regression tests.",
      domain: "testing",
      color: "#a3e635",
      tags: ["testing"],
      facets: { domain: ["testing"] },
      skillPath: "/skills/pytest/SKILL.md",
      bundlePath: "/skills/pytest",
      rootPath: "/skills",
      contentHash: "3",
      excerptCount: 1,
      referenceCount: 1,
      relationshipSummary: { incoming: 0, outgoing: 1, unresolved: 0, conflicts: 1 },
      backendRefs: []
    }
  ],
  edges: [
    {
      id: "router:requires:planner",
      source: "router",
      sourceName: "Router",
      target: "planner",
      targetName: "Planner",
      type: "requires",
      label: "requires",
      color: "#60a5fa"
    },
    {
      id: "pytest:conflicts:router",
      source: "pytest",
      sourceName: "Pytest",
      target: "router",
      targetName: "Router",
      type: "conflicts",
      label: "conflicts",
      color: "#f87171"
    }
  ],
  warnings: []
};

describe("graph transforms", () => {
  it("filters by domain and search", () => {
    const filters = { ...defaultFilters(atlas), domains: ["routing"], search: "plan" };
    expect([...filteredSkillIds(atlas, filters)].sort()).toEqual(["planner"]);
  });

  it("filters conflict-only skills", () => {
    const filters = { ...defaultFilters(atlas), conflictsOnly: true };
    expect([...filteredSkillIds(atlas, filters)].sort()).toEqual(["pytest", "router"]);
  });

  it("marks route preview nodes and selected path edges", () => {
    const result = layoutAtlasGraph(atlas, defaultFilters(atlas), "router", ["router", "planner"]);
    const router = result.nodes.find((node) => node.id === "router");
    const highlightedEdge = result.edges.find((edge) => edge.id === "router:requires:planner");

    expect(router?.data.routeRank).toBe(1);
    expect(router?.data.selected).toBe(true);
    expect(highlightedEdge?.animated).toBe(true);
  });
});
