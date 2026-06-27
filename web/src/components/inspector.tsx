import { useMemo } from "react";
import { Boxes, Sparkles } from "lucide-react";
import type { AtlasNodeRecord, AtlasPayload, DomainSummary, SkillDetail } from "../types";
import type { InspectorTab } from "../ui";
import { basename } from "../util";
import { StatRow, TagCloud } from "./primitives";

export function Inspector({
  atlas,
  selectedDomain,
  selectedNode,
  skillDetail,
  activeTab,
  onTabChange
}: {
  atlas: AtlasPayload;
  selectedDomain: DomainSummary | null;
  selectedNode: AtlasNodeRecord | null;
  skillDetail: SkillDetail | null;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}) {
  return (
    <aside className="inspector">
      {selectedNode ? (
        <SkillInspector node={selectedNode} detail={skillDetail} activeTab={activeTab} onTabChange={onTabChange} />
      ) : (
        <DomainInspector
          atlas={atlas}
          domain={selectedDomain ?? atlas.domains[0]}
          activeTab={activeTab}
          onTabChange={onTabChange}
        />
      )}
    </aside>
  );
}

function DomainInspector({
  atlas,
  domain,
  activeTab,
  onTabChange
}: {
  atlas: AtlasPayload;
  domain: DomainSummary;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}) {
  const { skills, topSkills, domainEdgeCount, density } = useMemo(() => {
    const domainSkills = atlas.nodes.filter((node) => node.domain === domain.id);
    const skillIds = new Set(domainSkills.map((skill) => skill.id));
    const ranked = [...domainSkills]
      .sort(
        (a, b) =>
          b.relationshipSummary.incoming +
          b.relationshipSummary.outgoing -
          (a.relationshipSummary.incoming + a.relationshipSummary.outgoing)
      )
      .slice(0, 5);
    const edgeCount = atlas.edges.filter((edge) => skillIds.has(edge.source)).length;
    return {
      skills: domainSkills,
      topSkills: ranked,
      domainEdgeCount: edgeCount,
      density: domainSkills.length ? (edgeCount / domainSkills.length).toFixed(2) : "0.00"
    };
  }, [atlas, domain.id]);
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
      <InspectorTabs activeTab={activeTab} onTabChange={onTabChange} />
      {activeTab === "overview" ? (
        <>
          <section className="inspector-block">
            <div className="block-label">Relationship Density</div>
            <div className="density-number">{density}<span>avg. connections / skill</span></div>
            <div className="density-meter"><span style={{ width: `${Math.min(Number(density) * 38, 100)}%` }} /></div>
          </section>
          <section className="inspector-block">
            <div className="block-label">Top Skills</div>
            <TopSkillsList skills={topSkills} />
          </section>
        </>
      ) : null}
      {activeTab === "skills" ? (
        <section className="inspector-block">
          <div className="block-label">Skills</div>
          <TopSkillsList skills={skills.slice(0, 12)} />
        </section>
      ) : null}
      {activeTab === "excerpts" ? (
        <section className="inspector-block">
          <div className="block-label">Tags / Facets</div>
          <TagCloud tags={[...new Set(skills.flatMap((skill) => skill.tags))].slice(0, 18)} />
        </section>
      ) : null}
      {activeTab === "stats" ? (
        <section className="inspector-block relationship-grid">
          <StatRow label="Skills" value={skills.length} />
          <StatRow label="Relationships" value={domainEdgeCount} />
          <StatRow label="Catalog Total" value={atlas.catalog.skillCount} />
        </section>
      ) : null}
    </>
  );
}

function SkillInspector({
  node,
  detail,
  activeTab,
  onTabChange
}: {
  node: AtlasNodeRecord;
  detail: SkillDetail | null;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}) {
  const excerpts = detail?.excerpts ?? [];
  const references = detail?.references ?? [];
  const backendRefs = detail?.backend_refs ?? node.backendRefs;
  const unresolvedRelationships = detail?.unresolved_relationships ?? [];
  const incomingRelationships = detail?.incoming_relationships ?? [];
  const outgoingRelationships = detail?.outgoing_relationships ?? [];
  return (
    <>
      <div className="inspector-header">
        <span className="domain-glyph" style={{ color: node.color }}><Boxes size={28} /></span>
        <div>
          <div className="section-label">Selected Skill</div>
          <h2>{node.name}</h2>
        </div>
      </div>
      <InspectorTabs activeTab={activeTab} onTabChange={onTabChange} />
      {activeTab === "overview" ? (
        <>
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
        </>
      ) : null}
      {activeTab === "skills" ? (
        <section className="inspector-block">
          <div className="block-label">Related Skills</div>
          <RelationshipList incoming={incomingRelationships} outgoing={outgoingRelationships} />
        </section>
      ) : null}
      {activeTab === "excerpts" ? (
        <>
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
        </>
      ) : null}
      {activeTab === "stats" ? (
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
      ) : null}
    </>
  );
}

function TopSkillsList({ skills }: { skills: AtlasNodeRecord[] }) {
  return (
    <div className="top-skills">
      {skills.map((skill, index) => (
        <div key={skill.id} className="top-skill-row">
          <span>{index + 1}</span>
          <strong>{skill.name}</strong>
          <div className="mini-dots">
            {skill.tags.slice(0, 4).map((tag) => <i key={tag} style={{ background: skill.color }} />)}
          </div>
        </div>
      ))}
      {!skills.length ? <div className="muted-row">No skills in this domain.</div> : null}
    </div>
  );
}

function RelationshipList({
  incoming,
  outgoing
}: {
  incoming: SkillDetail["incoming_relationships"];
  outgoing: SkillDetail["outgoing_relationships"];
}) {
  const rows = [
    ...incoming.map((relationship) => ({
      key: `incoming:${relationship.id}`,
      label: relationship.type.replace("_", " "),
      name: relationship.sourceName
    })),
    ...outgoing.map((relationship) => ({
      key: `outgoing:${relationship.id}`,
      label: relationship.type.replace("_", " "),
      name: relationship.targetName
    }))
  ];
  return (
    <div className="reference-list">
      {rows.map((row) => (
        <div key={row.key} className="reference-row">
          <span>{row.label}</span>
          <strong>{row.name}</strong>
        </div>
      ))}
      {!rows.length ? <div className="muted-row">No related skills recorded.</div> : null}
    </div>
  );
}

function InspectorTabs({
  activeTab,
  onTabChange
}: {
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
}) {
  return (
    <div className="inspector-tabs">
      <button className={activeTab === "overview" ? "active" : ""} onClick={() => onTabChange("overview")} type="button">Overview</button>
      <button className={activeTab === "skills" ? "active" : ""} onClick={() => onTabChange("skills")} type="button">Skills</button>
      <button className={activeTab === "excerpts" ? "active" : ""} onClick={() => onTabChange("excerpts")} type="button">Excerpts</button>
      <button className={activeTab === "stats" ? "active" : ""} onClick={() => onTabChange("stats")} type="button">Stats</button>
    </div>
  );
}
