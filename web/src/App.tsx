import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type OnMoveEnd,
  type ReactFlowInstance
} from "@xyflow/react";
import { fetchAtlas, fetchSkill, postRoutePreview } from "./api";
import { defaultFilters, layoutAtlasGraph, type AtlasFilters } from "./graph";
import type { AtlasPayload, RoutePreview, SkillDetail } from "./types";
import type { InspectorTab, NavSection } from "./ui";
import { resolveSelectedId, storageKey } from "./util";
import { EmptyGraphState, StatusScreen } from "./components/primitives";
import { LeftPanel, NavRail, RelationshipLegend, TopBar } from "./components/panels";
import { Inspector } from "./components/inspector";
import { RoutePreviewStrip } from "./components/route-preview";
import { miniMapNodeColor, nodeTypes } from "./components/graph-nodes";

export function App() {
  const [atlas, setAtlas] = useState<AtlasPayload | null>(null);
  const [filters, setFilters] = useState<AtlasFilters | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null);
  const [routeInput, setRouteInput] = useState("Build an MCP server that exposes routing tools");
  const [routePreview, setRoutePreview] = useState<RoutePreview | null>(null);
  const [routeHighlightEnabled, setRouteHighlightEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [routeLoading, setRouteLoading] = useState(false);
  const [refreshingAtlas, setRefreshingAtlas] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [activeNav, setActiveNav] = useState<NavSection>("map");
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview");
  const leftPanelRef = useRef<HTMLElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const routeInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchAtlas()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        const nextFilters = defaultFilters(payload);
        const storedSelected = localStorage.getItem(storageKey(payload.catalog.fingerprint));
        setAtlas(payload);
        setFilters(nextFilters);
        setSelectedId(resolveSelectedId(payload, storedSelected));
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // Persist the selection. Depends on atlas (for the fingerprint) and selectedId.
  useEffect(() => {
    if (atlas && selectedId) {
      localStorage.setItem(storageKey(atlas.catalog.fingerprint), selectedId);
    }
  }, [atlas, selectedId]);

  // Fetch skill detail only when the selection changes — not on every atlas refresh.
  useEffect(() => {
    if (!selectedId || selectedId.startsWith("domain:")) {
      setSkillDetail(null);
      return;
    }
    let cancelled = false;
    fetchSkill(selectedId)
      .then((detail) => {
        if (!cancelled) {
          setSkillDetail(detail);
        }
      })
      // Graceful fallback: the inspector still renders node-level data when the
      // detail request fails (e.g. the skill vanished after a catalog re-index).
      .catch(() => {
        if (!cancelled) {
          setSkillDetail(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const routeOrder = useMemo(
    () => (routeHighlightEnabled ? routePreview?.suggested_order ?? [] : []),
    [routeHighlightEnabled, routePreview]
  );
  const graph = useMemo(() => {
    if (!atlas || !filters) {
      return null;
    }
    return layoutAtlasGraph(atlas, filters, selectedId, routeOrder);
  }, [atlas, filters, selectedId, routeOrder]);

  const selectedDomainId = selectedId?.startsWith("domain:") ? selectedId.replace("domain:", "") : null;
  const selectedDomain = atlas?.domains.find((domain) => domain.id === selectedDomainId) ?? null;
  const selectedNode = atlas?.nodes.find((node) => node.id === selectedId) ?? null;

  const onMoveEnd: OnMoveEnd = (_, viewport) => {
    if (atlas) {
      localStorage.setItem(`skillroute-atlas-view:${atlas.catalog.fingerprint}`, JSON.stringify(viewport));
    }
  };

  async function runRoutePreview() {
    if (!routeInput.trim()) {
      return;
    }
    setRouteLoading(true);
    try {
      const preview = await postRoutePreview(routeInput.trim(), 5);
      setRoutePreview(preview);
      setRouteHighlightEnabled(true);
      setSelectedId(preview.suggested_order[0] ?? selectedId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Route preview failed");
    } finally {
      setRouteLoading(false);
    }
  }

  async function refreshAtlas() {
    setRefreshingAtlas(true);
    try {
      const payload = await fetchAtlas();
      setAtlas(payload);
      setFilters(defaultFilters(payload));
      setSelectedId((current) => resolveSelectedId(payload, current));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Atlas refresh failed");
    } finally {
      setRefreshingAtlas(false);
    }
  }

  function relayoutGraph() {
    void flowInstance?.fitView({ padding: 0.18, duration: 260 });
  }

  function selectNavSection(section: NavSection) {
    setActiveNav(section);
    if (section === "map") {
      relayoutGraph();
      return;
    }
    if (section === "atlas") {
      searchInputRef.current?.focus();
      return;
    }
    if (section === "routes") {
      routeInputRef.current?.scrollIntoView({ block: "nearest" });
      routeInputRef.current?.focus();
      return;
    }
    leftPanelRef.current?.scrollTo({ top: leftPanelRef.current.scrollHeight, behavior: "smooth" });
  }

  if (loading) {
    return <StatusScreen title="Loading Skill Atlas" detail="Reading the local catalog and building the map." />;
  }

  if (error && !atlas) {
    return <StatusScreen title="Skill Atlas unavailable" detail={error} />;
  }

  if (!atlas || !filters || !graph) {
    return <StatusScreen title="No catalog data" detail="Index skills, then launch `skillroute ui` again." />;
  }

  return (
    <div className="app-shell">
      <NavRail activeSection={activeNav} onSelect={selectNavSection} />
      <LeftPanel
        atlas={atlas}
        filters={filters}
        onFiltersChange={setFilters}
        panelRef={leftPanelRef}
        searchInputRef={searchInputRef}
      />
      <main className="map-surface">
        <TopBar
          atlas={atlas}
          onRefresh={() => void refreshAtlas()}
          onRelayout={relayoutGraph}
          refreshing={refreshingAtlas}
        />
        <div className="graph-frame">
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            minZoom={0.35}
            maxZoom={1.7}
            onInit={setFlowInstance}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(`domain:${atlas.domains[0]?.id ?? "uncategorized"}`)}
            onMoveEnd={onMoveEnd}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#183244" gap={32} size={1} />
            <MiniMap
              className="mini-map"
              nodeColor={miniMapNodeColor}
              maskColor="rgba(2, 8, 23, 0.72)"
              pannable
              zoomable
            />
            <Controls className="flow-controls" showInteractive={false} />
          </ReactFlow>
          <RelationshipLegend atlas={atlas} />
          {graph.visibleSkillIds.size === 0 ? <EmptyGraphState /> : null}
          <div className="canvas-help">Drag to pan • Scroll to zoom • Click a node to inspect</div>
        </div>
      </main>
      <Inspector
        atlas={atlas}
        selectedDomain={selectedDomain}
        selectedNode={selectedNode}
        skillDetail={skillDetail}
        activeTab={inspectorTab}
        onTabChange={setInspectorTab}
      />
      <RoutePreviewStrip
        routeInput={routeInput}
        setRouteInput={setRouteInput}
        routePreview={routePreview}
        routeLoading={routeLoading}
        routeHighlightEnabled={routeHighlightEnabled}
        setRouteHighlightEnabled={setRouteHighlightEnabled}
        runRoutePreview={runRoutePreview}
        inputRef={routeInputRef}
      />
    </div>
  );
}
