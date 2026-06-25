export interface CatalogSummary {
  path: string;
  skillCount: number;
  domainCount: number;
  relationshipCount: number;
  unresolvedRelationshipCount: number;
  orphanCount: number;
  conflictCount: number;
  backendRefCounts: Record<string, number>;
  fingerprint: string;
}

export interface DomainSummary {
  id: string;
  name: string;
  count: number;
  color: string;
}

export interface RelationshipTypeSummary {
  type: string;
  count: number;
  color: string;
}

export interface AtlasNodeRecord {
  id: string;
  name: string;
  description: string;
  domain: string;
  color: string;
  tags: string[];
  facets: Record<string, string[]>;
  skillPath: string;
  bundlePath: string;
  rootPath: string;
  contentHash: string;
  excerptCount: number;
  referenceCount: number;
  relationshipSummary: {
    incoming: number;
    outgoing: number;
    unresolved: number;
    conflicts: number;
  };
  backendRefs: BackendRef[];
}

export interface AtlasEdgeRecord {
  id: string;
  source: string;
  sourceName: string;
  target: string;
  targetName: string;
  type: string;
  label: string;
  color: string;
}

export interface AtlasWarning {
  skillId: string;
  relationshipType: string;
  target: string;
}

export interface AtlasPayload {
  catalog: CatalogSummary;
  domains: DomainSummary[];
  relationshipTypes: RelationshipTypeSummary[];
  nodes: AtlasNodeRecord[];
  edges: AtlasEdgeRecord[];
  warnings: AtlasWarning[];
}

export interface BackendRef {
  backend: string;
  ref: string;
  status: string;
  updated_at: string;
}

export interface SkillExcerpt {
  kind: string;
  text: string;
  source_path: string;
  start_line: number;
  end_line: number;
}

export interface SkillReference {
  kind: string;
  path: string;
}

export interface SkillDetail {
  id: string;
  name: string;
  description: string;
  domain: string;
  tags: string[];
  facets: Record<string, string[]>;
  skill_path: string;
  bundle_path: string;
  root_path: string;
  content_hash: string;
  excerpts: SkillExcerpt[];
  references: SkillReference[];
  backend_refs: BackendRef[];
  incoming_relationships: AtlasEdgeRecord[];
  outgoing_relationships: AtlasEdgeRecord[];
  unresolved_relationships: Array<{ type: string; target: string }>;
  relationship_summary: {
    incoming: number;
    outgoing: number;
  };
}

export interface RouteCandidate {
  skill_id: string;
  name: string;
  description: string;
  confidence: number;
  suggested_position: number;
}

export interface RoutePreview {
  request: string;
  candidates: RouteCandidate[];
  suggested_order: string[];
  clarification_needed: boolean;
  clarification_questions: string[];
}
