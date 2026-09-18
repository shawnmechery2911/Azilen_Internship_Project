import { ArrowUpRight } from "lucide-react";

export function ApprovalRow({
  initials,
  name,
  type,
  detail,
  age,
  tone,
  onClick,
}: {
  initials: string;
  name: string;
  type: string;
  detail: string;
  age: string;
  tone: string;
  onClick: () => void;
}) {
  return (
    <button className="approval-row" onClick={onClick}>
      <div className={`partner-avatar ${tone}`}>{initials}</div>
      <div className="row-copy">
        <strong>{name}</strong>
        <span>{type}</span>
      </div>
      <div className="row-detail">
        <strong>{detail}</strong>
        <span>{age}</span>
      </div>
      <ArrowUpRight size={16} className="row-arrow" />
    </button>
  );
}
