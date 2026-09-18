import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  delta,
  note,
  icon,
  tone,
  warning = false,
}: {
  label: string;
  value: string;
  delta: string;
  note: string;
  icon: ReactNode;
  tone: string;
  warning?: boolean;
}) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <strong>{value}</strong>
      <div className="metric-foot">
        <span className={warning ? "warning" : "positive"}>{delta}</span>
        <span>{note}</span>
      </div>
    </article>
  );
}
