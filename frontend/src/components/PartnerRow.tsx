export function PartnerRow({
  initials,
  name,
  kind,
  value,
  tone,
  status,
}: {
  initials: string;
  name: string;
  kind: string;
  value: string;
  tone: string;
  status?: string;
}) {
  return (
    <div className="partner-row">
      <div className={`partner-avatar ${tone}`}>{initials}</div>
      <div className="row-copy">
        <strong>{name}</strong>
        <span>{kind}</span>
      </div>
      <div className="partner-result">
        <strong>{value}</strong>
        <span className={status ? "warning" : "positive"}>
          {status || "healthy"}
        </span>
      </div>
      <span className={`status-bar ${status ? "status-warning" : ""}`}></span>
    </div>
  );
}
