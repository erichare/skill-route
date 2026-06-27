import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { DomainNodeData, SkillNodeData } from "../graph";

export const nodeTypes = {
  skill: SkillNode,
  domain: DomainNode
};

export function SkillNode({ data }: NodeProps<Node<SkillNodeData>>) {
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

export function DomainNode({ data }: NodeProps<Node<DomainNodeData>>) {
  return (
    <div className={`domain-node ${data.selected ? "selected" : ""}`} style={{ color: data.color }}>
      <strong>{data.name}</strong>
      <span>{data.count} skills</span>
    </div>
  );
}

export function miniMapNodeColor(node: Node): string {
  const data = node.data as Partial<SkillNodeData & DomainNodeData>;
  return data.record?.color ?? data.color ?? "#64748b";
}
