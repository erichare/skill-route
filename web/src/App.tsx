import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
  type OnMoveEnd
} from "@xyflow/react";
import {
  Boxes,
  ChevronRight,
  Database,
  Layers3,
  Map,
  Network,
  RefreshCcw,
  Route,
  Search,
  Settings2,
  Sparkles,
  Waypoints
} from "lucide-react";
import { fetchAtlas, fetchSkill, postRoutePreview } from "./api";
import {
  defaultFilters,
  layoutAtlasGraph,
  type AtlasFilters,
  type DomainNodeData,
  type SkillNodeData
} from "./graph";
import type { AtlasNodeRecord, AtlasPayload, DomainSummary, RoutePreview, SkillDetail } from "./types";

const nodeTypes = {
  skill: SkillNode,
  domain: DomainNode
};

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
  const [error, setError] = useState<string | null>(null);

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
        setSelectedId(storedSelected || `domain:${payload.domains[0]?.id ?? "uncategorized"}`);
        setError(null);
      })
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!atlas || !selectedId) {
      return;
    }
    localStorage.setItem(storageKey(atlas.catalog.fingerprint), selectedId);
    if (selectedId.startsWith("domain:")) {
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
      .catch(() => setSkillDetail(null));
    return () => {
      cancelled = true;
    };
  }, [atlas, selectedId]);

  const routeOrder = routeHighlightEnabled ? routePreview?.suggested_order ?? [] : [];
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
      <NavRail />
      <LeftPanel atlas={atlas} filters={filters} onFiltersChange={setFilters} />
      <main className="map-surface">
        <TopBar atlas={atlas} />
        <div className="graph-frame">
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            minZoom={0.35}
            maxZoom={1.7}
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
          <div className="canvas-help">Drag to pan • Scroll to zoom • Click a node to inspect</div>
        </div>
      </main>
      <Inspector
        atlas={atlas}
        selectedDomain={selectedDomain}
        selectedNode={selectedNode}
        skillDetail={skillDetail}
      />
      <RoutePreviewStrip
        routeInput={routeInput}
        setRouteInput={setRouteInput}
        routePreview={routePreview}
        routeLoading={routeLoading}
        routeHighlightEnabled={routeHighlightEnabled}
        setRouteHighlightEnabled={setRouteHighlightEnabled}
        runRoutePreview={runRoutePreview}
      />
    </div>
  );
}

function NavRail() {
  return (
    <aside className="nav-rail">
      <div className="brand-mark">
        <Network size={25} />
      </div>
      <RailButton icon={<Map size={19} />} label="Map" active />
      <RailButton icon={<Layers3 size={19} />} label="Atlas" />
      <RailButton icon={<Route size={19} />} label="Routes" />
      <RailButton icon={<Database size={19} />} label="Catalog" />
      <div className="rail-spacer" />
      <RailButton icon={<Settings2 size={19} />} label="Settings" />
      <div className="local-first">
        <span />
        Local-first
      </div>
    </aside>
  );
}

function RailButton({ icon, label, active = false }: { icon: React.ReactNode; label: string; active?: boolean }) {
  return (
    <button className={`rail-button ${active ? "active" : ""}`} title={label} type="button">
      {icon}
      <span>{label}</span>
    </button>
  );
}

function LeftPanel({
  atlas,
  filters,
  onFiltersChange
}: {
  atlas: AtlasPayload;
  filters: AtlasFilters;
  onFiltersChange: (filters: AtlasFilters) => void;
}) {
  const allDomainsSelected = filters.domains.length === atlas.domains.length;
  return (
    <aside className="left-panel">
      <div className="panel-section title-section">
        <h1>SkillRoute</h1>
      </div>
      <div className="panel-section">
        <div className="section-label">Atlas Controls</div>
        <label className="search-box">
          <Search size={15} />
          <input
            value={filters.search}
            onChange={(event) => onFiltersChange({ ...filters, search: event.target.value })}
            placeholder="Search skills, facets, tags..."
          />
          <kbd>/</kbd>
        </label>
      </div>
      <div className="panel-section">
        <div className="section-label">Graph Mode</div>
        <div className="segmented">
          <button className="active" type="button">Facet Nebula</button>
          <button type="button">Skill Graph</button>
          <button type="button">Matrix</button>
        </div>
      </div>
      <div className="panel-section grow">
        <div className="section-heading">
          <span>Facets / Domains</span>
          <button
            type="button"
            onClick={() =>
              onFiltersChange({
                ...filters,
                domains: allDomainsSelected ? [atlas.domains[0]?.id ?? "uncategorized"] : atlas.domains.map((domain) => domain.id)
              })
            }
          >
            {allDomainsSelected ? "Focus" : "Select all"}
          </button>
        </div>
        <div className="domain-list">
          {atlas.domains.map((domain) => (
            <ToggleRow
              key={domain.id}
              color={domain.color}
              label={domain.name}
              value={domain.count}
              checked={filters.domains.includes(domain.id)}
              onChange={() => {
                const next = filters.domains.includes(domain.id)
                  ? filters.domains.filter((item) => item !== domain.id)
                  : [...filters.domains, domain.id];
                onFiltersChange({ ...filters, domains: next.length ? next : [domain.id] });
              }}
            />
          ))}
        </div>
      </div>
      <div className="panel-section">
        <div className="section-label">Relationship Types</div>
        <div className="relationship-toggle-list">
          {atlas.relationshipTypes.map((relationship) => (
            <ToggleRow
              key={relationship.type}
              color={relationship.color}
              label={relationship.type.replace("_", " ")}
              value={relationship.count}
              checked={filters.relationshipTypes.includes(relationship.type)}
              onChange={() => {
                const next = filters.relationshipTypes.includes(relationship.type)
                  ? filters.relationshipTypes.filter((item) => item !== relationship.type)
                  : [...filters.relationshipTypes, relationship.type];
                onFiltersChange({ ...filters, relationshipTypes: next.length ? next : [relationship.type] });
              }}
            />
          ))}
        </div>
      </div>
      <div className="panel-section">
        <div className="section-label">Filters</div>
        <SwitchRow
          label="Orphans only"
          value={atlas.catalog.orphanCount}
          checked={filters.orphansOnly}
          onChange={() => onFiltersChange({ ...filters, orphansOnly: !filters.orphansOnly })}
        />
        <SwitchRow
          label="Conflicts only"
          value={atlas.catalog.conflictCount}
          checked={filters.conflictsOnly}
          onChange={() => onFiltersChange({ ...filters, conflictsOnly: !filters.conflictsOnly })}
        />
      </div>
      <CatalogStats atlas={atlas} />
    </aside>
  );
}

function ToggleRow({
  color,
  label,
  value,
  checked,
  onChange
}: {
  color: string;
  label: string;
  value: number;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button className="toggle-row" type="button" onClick={onChange}>
      <span className={`checkbox ${checked ? "checked" : ""}`}>{checked ? "✓" : ""}</span>
      <span className="color-dot" style={{ background: color, boxShadow: `0 0 16px ${color}` }} />
      <span className="row-label">{label}</span>
      <span className="row-value">{value}</span>
    </button>
  );
}

function SwitchRow({
  label,
  value,
  checked,
  onChange
}: {
  label: string;
  value: number;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <button className="switch-row" type="button" onClick={onChange}>
      <span className={`switch ${checked ? "on" : ""}`} />
      <span>{label}</span>
      <strong>{value}</strong>
    </button>
  );
}

function CatalogStats({ atlas }: { atlas: AtlasPayload }) {
  return (
    <div className="catalog-card">
      <div className="section-label">Catalog Stats</div>
      <StatRow label="Total Skills" value={atlas.catalog.skillCount} />
      <StatRow label="Facets" value={atlas.catalog.domainCount} />
      <StatRow label="Relationships" value={atlas.catalog.relationshipCount} />
      <StatRow label="Orphans" value={atlas.catalog.orphanCount} color="#fb923c" />
      <StatRow label="Conflicts" value={atlas.catalog.conflictCount} color="#f87171" />
      <StatRow label="Unresolved" value={atlas.catalog.unresolvedRelationshipCount} />
      <div className="stats-footer">Backend {Object.keys(atlas.catalog.backendRefCounts)[0] ?? "local-token:indexed"}</div>
    </div>
  );
}

function StatRow({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="stat-row">
      <span>{color ? <i style={{ background: color }} /> : null}{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TopBar({ atlas }: { atlas: AtlasPayload }) {
  return (
    <header className="top-bar">
      <div>
        <div className="top-title">Skill Universe</div>
        <div className="top-meta">
          {atlas.catalog.skillCount} skills • {atlas.catalog.relationshipCount} relationships • {atlas.catalog.path}
        </div>
      </div>
      <div className="top-actions">
        <button type="button">Layout: Radial</button>
        <button aria-label="Relayout" type="button"><Waypoints size={17} /></button>
        <button aria-label="Refresh" type="button"><RefreshCcw size={17} /></button>
      </div>
    </header>
  );
}

function RelationshipLegend({ atlas }: { atlas: AtlasPayload }) {
  return (
    <div className="legend">
      <div className="section-label">Legend</div>
      {atlas.relationshipTypes.map((relationship) => (
        <div key={relationship.type} className="legend-row">
          <span style={{ background: relationship.color }} />
          {relationship.type.replace("_", " ")}
        </div>
      ))}
      <div className="legend-row selected"><span /> selected path</div>
    </div>
  );
}

function Inspector({
  atlas,
  selectedDomain,
  selectedNode,
  skillDetail
}: {
  atlas: AtlasPayload;
  selectedDomain: DomainSummary | null;
  selectedNode: AtlasNodeRecord | null;
  skillDetail: SkillDetail | null;
}) {
  return (
    <aside className="inspector">
      {selectedNode ? (
        <SkillInspector node={selectedNode} detail={skillDetail} />
      ) : (
        <DomainInspector atlas={atlas} domain={selectedDomain ?? atlas.domains[0]} />
      )}
    </aside>
  );
}

function DomainInspector({ atlas, domain }: { atlas: AtlasPayload; domain: DomainSummary }) {
  const skills = atlas.nodes.filter((node) => node.domain === domain.id);
  const topSkills = [...skills]
    .sort(
      (a, b) =>
        b.relationshipSummary.incoming +
        b.relationshipSummary.outgoing -
        (a.relationshipSummary.incoming + a.relationshipSummary.outgoing)
    )
    .slice(0, 5);
  const density = skills.length ? (atlas.edges.filter((edge) => skills.some((skill) => skill.id === edge.source)).length / skills.length).toFixed(2) : "0.00";
  return (
    <>
      <div className="inspector-header">
        <span className="domain-glyph" style={{ color: domain.color }}><Sparkles size={29} /></span>
        <div>
          <div className="section-label">Selected Domain</div>
          <h2>{domain.name}</h2>
        </div>
        <span className="count-pill">{domain.count} skills</span>
      </div>
      <InspectorTabs />
      <section className="inspector-block">
        <div className="block-label">Relationship Density</div>
        <div className="density-number">{density}<span>avg. connections / skill</span></div>
        <div className="density-meter"><span style={{ width: `${Math.min(Number(density) * 38, 100)}%` }} /></div>
      </section>
      <section className="inspector-block">
        <div className="block-label">Top Skills</div>
        <div className="top-skills">
          {topSkills.map((skill, index) => (
            <div key={skill.id} className="top-skill-row">
              <span>{index + 1}</span>
              <strong>{skill.name}</strong>
              <div className="mini-dots">
                {skill.tags.slice(0, 4).map((tag) => <i key={tag} style={{ background: skill.color }} />)}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="inspector-block">
        <div className="block-label">Tags / Facets</div>
        <TagCloud tags={[...new Set(skills.flatMap((skill) => skill.tags))].slice(0, 10)} />
      </section>
    </>
  );
}

function SkillInspector({ node, detail }: { node: AtlasNodeRecord; detail: SkillDetail | null }) {
  const excerpts = detail?.excerpts ?? [];
  const references = detail?.references ?? [];
  const backendRefs = detail?.backend_refs ?? node.backendRefs;
  const unresolvedRelationships = detail?.unresolved_relationships ?? [];
  return (
    <>
      <div className="inspector-header">
        <span className="domain-glyph" style={{ color: node.color }}><Boxes size={28} /></span>
        <div>
          <div className="section-label">Selected Skill</div>
          <h2>{node.name}</h2>
        </div>
      </div>
      <InspectorTabs />
      <section className="inspector-block">
        <p className="skill-description">{node.description}</p>
        <TagCloud tags={node.tags} />
      </section>
      <section className="inspector-block relationship-grid">
        <StatRow label="Incoming" value={detail?.relationship_summary.incoming ?? node.relationshipSummary.incoming} />
        <StatRow label="Outgoing" value={detail?.relationship_summary.outgoing ?? node.relationshipSummary.outgoing} />
        <StatRow label="Unresolved" value={node.relationshipSummary.unresolved} color="#f59e0b" />
      </section>
      {unresolvedRelationships.length ? (
        <section className="inspector-block warning-list">
          <div className="block-label">Unresolved Relationships</div>
          {unresolvedRelationships.map((relationship) => (
            <div key={`${relationship.type}:${relationship.target}`} className="warning-row">
              <span>{relationship.type.replace("_", " ")}</span>
              <strong>{relationship.target}</strong>
            </div>
          ))}
        </section>
      ) : null}
      <section className="inspector-block">
        <div className="block-label">Excerpt</div>
        <p className="excerpt">{excerpts[0]?.text ?? "No excerpt available for this skill."}</p>
      </section>
      <section className="inspector-block">
        <div className="block-label">Source References</div>
        <div className="reference-list">
          {references.slice(0, 4).map((reference) => (
            <div key={reference.path} className="reference-row">
              <span>{reference.kind}</span>
              <strong>{basename(reference.path)}</strong>
            </div>
          ))}
          {!references.length ? <div className="muted-row">No source references loaded.</div> : null}
        </div>
      </section>
      <section className="inspector-block">
        <div className="block-label">Backend Index Status</div>
        {backendRefs.length ? (
          backendRefs.map((ref) => (
            <div key={`${ref.backend}:${ref.ref}`} className="backend-row">
              <span className="status-dot" />
              <strong>{ref.status}</strong>
              <span>{ref.backend}</span>
            </div>
          ))
        ) : (
          <div className="muted-row">No backend refs recorded.</div>
        )}
      </section>
    </>
  );
}

function InspectorTabs() {
  return (
    <div className="inspector-tabs">
      <button className="active" type="button">Overview</button>
      <button type="button">Skills</button>
      <button type="button">Excerpts</button>
      <button type="button">Stats</button>
    </div>
  );
}

function TagCloud({ tags }: { tags: string[] }) {
  return (
    <div className="tag-cloud">
      {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>no tags</span>}
    </div>
  );
}

function RoutePreviewStrip({
  routeInput,
  setRouteInput,
  routePreview,
  routeLoading,
  routeHighlightEnabled,
  setRouteHighlightEnabled,
  runRoutePreview
}: {
  routeInput: string;
  setRouteInput: (value: string) => void;
  routePreview: RoutePreview | null;
  routeLoading: boolean;
  routeHighlightEnabled: boolean;
  setRouteHighlightEnabled: (value: boolean) => void;
  runRoutePreview: () => void;
}) {
  const candidates = routePreview?.candidates ?? [];
  return (
    <section className="route-preview">
      <div className="route-toolbar">
        <div>
          <strong>Route Preview</strong>
          <input
            value={routeInput}
            onChange={(event) => setRouteInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void runRoutePreview();
              }
            }}
            placeholder="Describe an agent task..."
          />
        </div>
        <button className="preview-button" type="button" onClick={() => void runRoutePreview()}>
          {routeLoading ? "Routing..." : "Preview"}
        </button>
        <button
          className={`path-toggle ${routeHighlightEnabled ? "on" : ""}`}
          type="button"
          onClick={() => setRouteHighlightEnabled(!routeHighlightEnabled)}
        >
          Highlight Path
        </button>
      </div>
      <div className="route-steps">
        {(candidates.length ? candidates : placeholderSteps()).map((candidate, index) => (
          <div key={candidate.skill_id} className={`route-step ${index === 0 && candidates.length ? "active" : ""}`}>
            <span>{index + 1}</span>
            <div>
              <strong>{candidate.name}</strong>
              <small>{candidate.skill_id}</small>
            </div>
            {index < 4 ? <ChevronRight size={20} /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function SkillNode({ data }: NodeProps<Node<SkillNodeData>>) {
  const size = data.selected ? 21 : data.routeRank ? 18 : 13;
  return (
    <div
      className={`skill-node ${data.selected ? "selected" : ""} ${data.routeRank ? "route-hit" : ""}`}
      style={{
        width: size,
        height: size,
        background: data.record.color,
        boxShadow: `0 0 ${data.selected ? 24 : 16}px ${data.record.color}`
      }}
      title={data.record.name}
    >
      <Handle className="node-handle target-handle" type="target" position={Position.Top} />
      <Handle className="node-handle source-handle" type="source" position={Position.Bottom} />
      {data.routeRank ? <span>{data.routeRank}</span> : null}
      {data.selected ? <div className="node-popover"><strong>{data.record.name}</strong><small>{data.record.domain}</small></div> : null}
    </div>
  );
}

function miniMapNodeColor(node: Node): string {
  const data = node.data as Partial<SkillNodeData & DomainNodeData>;
  return data.record?.color ?? data.color ?? "#64748b";
}

function DomainNode({ data }: NodeProps<Node<DomainNodeData>>) {
  return (
    <div className={`domain-node ${data.selected ? "selected" : ""}`} style={{ color: data.color }}>
      <strong>{data.name}</strong>
      <span>{data.count} skills</span>
    </div>
  );
}

function StatusScreen({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="status-screen">
      <div className="brand-mark"><Network size={28} /></div>
      <h1>{title}</h1>
      <p>{detail}</p>
    </div>
  );
}

function placeholderSteps() {
  return [
    { skill_id: "route.preview", name: "Enter Request" },
    { skill_id: "candidate.retrieve", name: "Retrieve Context" },
    { skill_id: "skill.highlight", name: "Highlight Skills" },
    { skill_id: "inspect.evidence", name: "Inspect Evidence" },
    { skill_id: "apply.route", name: "Use Route" }
  ];
}

function basename(path: string) {
  return path.split("/").pop() ?? path;
}

function storageKey(fingerprint: string) {
  return `skillroute-atlas-selected:${fingerprint}`;
}
