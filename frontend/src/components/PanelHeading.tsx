import type { ReactNode } from "react";

export function PanelHeading({
  kicker,
  title,
  action,
}: {
  kicker: string;
  title: string;
  action: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div>
        <span className="section-kicker">{kicker}</span>
        <h2>{title}</h2>
      </div>
      {action}
    </div>
  );
}
