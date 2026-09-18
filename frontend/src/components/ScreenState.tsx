export function Loading({ label = "Loading..." }: { label?: string }) {
  return <div className="panel screen-state">{label}</div>;
}
export function EmptyState({ label }: { label: string }) {
  return <div className="panel screen-state">{label}</div>;
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
