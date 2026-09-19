/** A placeholder shaped like the rows it stands in for, so the layout does not
 *  jump when the data lands. `label` is announced to screen readers; sighted
 *  users get the shape instead, which says more than the word "Loading". */
export function Loading({
  label = "Loading...",
  rows = 4,
}: {
  label?: string;
  rows?: number;
}) {
  return (
    <div className="panel" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="skeleton skeleton-title" />
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index} aria-hidden="true">
          <span className="skeleton" />
          <span className="skeleton" style={{ width: `${70 - index * 6}%` }} />
          <span className="skeleton" />
          <span className="skeleton" />
        </div>
      ))}
    </div>
  );
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
