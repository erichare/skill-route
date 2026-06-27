import type { AtlasPayload } from "./types";

export function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

export function storageKey(fingerprint: string): string {
  return `skillroute-atlas-selected:${fingerprint}`;
}

export function resolveSelectedId(payload: AtlasPayload, preferredId: string | null): string {
  if (preferredId?.startsWith("domain:")) {
    const domainId = preferredId.replace("domain:", "");
    if (payload.domains.some((domain) => domain.id === domainId)) {
      return preferredId;
    }
  }
  if (preferredId && payload.nodes.some((node) => node.id === preferredId)) {
    return preferredId;
  }
  return `domain:${payload.domains[0]?.id ?? "uncategorized"}`;
}
