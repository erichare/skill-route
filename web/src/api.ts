import type { AtlasPayload, RoutePreview, SkillDetail } from "./types";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return (await response.json()) as T;
}

export function fetchAtlas(): Promise<AtlasPayload> {
  return requestJson<AtlasPayload>("/api/atlas");
}

export function fetchSkill(skillId: string): Promise<SkillDetail> {
  return requestJson<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`);
}

export function postRoutePreview(request: string, limit = 5): Promise<RoutePreview> {
  return requestJson<RoutePreview>("/api/route-preview", {
    method: "POST",
    body: JSON.stringify({ request, limit })
  });
}
