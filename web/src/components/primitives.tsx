import { Network } from "lucide-react";

export function ToggleRow({
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

export function SwitchRow({
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

export function StatRow({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className="stat-row">
      <span>{color ? <i style={{ background: color }} /> : null}{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function TagCloud({ tags }: { tags: string[] }) {
  return (
    <div className="tag-cloud">
      {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>no tags</span>}
    </div>
  );
}

export function EmptyGraphState() {
  return (
    <div className="empty-graph-state">
      <strong>No matching skills</strong>
      <span>Adjust search or filters to bring the graph back.</span>
    </div>
  );
}

export function StatusScreen({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="status-screen">
      <div className="brand-mark"><Network size={28} /></div>
      <h1>{title}</h1>
      <p>{detail}</p>
    </div>
  );
}
