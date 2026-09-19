export function Loading({ label = "Loading..." }: { label?: string }) {
  return <div className="panel screen-state">{label}</div>;
}
/** Plain text, because this nearly always sits inside a panel already - giving
 *  it its own card produced a box drawn inside a box. */
export function EmptyState({ label }: { label: string }) {
  return <p className="empty-note">{label}</p>;
}
export function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="panel screen-state">
      <strong>Could not load this screen</strong>
      <p>{message}</p>
      <button className="secondary-button" onClick={retry}>
        Retry
      </button>
    </div>
  );
}
