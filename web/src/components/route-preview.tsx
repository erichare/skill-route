import { type RefObject } from "react";
import { ChevronRight } from "lucide-react";
import type { RoutePreview } from "../types";

export function RoutePreviewStrip({
  routeInput,
  setRouteInput,
  routePreview,
  routeLoading,
  routeHighlightEnabled,
  setRouteHighlightEnabled,
  runRoutePreview,
  inputRef
}: {
  routeInput: string;
  setRouteInput: (value: string) => void;
  routePreview: RoutePreview | null;
  routeLoading: boolean;
  routeHighlightEnabled: boolean;
  setRouteHighlightEnabled: (value: boolean) => void;
  runRoutePreview: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const candidates = routePreview?.candidates ?? [];
  return (
    <section className="route-preview">
      <div className="route-toolbar">
        <div>
          <strong>Route Preview</strong>
          <input
            ref={inputRef}
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

function placeholderSteps() {
  return [
    { skill_id: "route.preview", name: "Enter Request" },
    { skill_id: "candidate.retrieve", name: "Retrieve Context" },
    { skill_id: "skill.highlight", name: "Highlight Skills" },
    { skill_id: "inspect.evidence", name: "Inspect Evidence" },
    { skill_id: "apply.route", name: "Use Route" }
  ];
}
