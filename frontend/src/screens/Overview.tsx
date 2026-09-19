import { useEffect, useMemo, useState } from "react";
import {
  getActivity,
  getAiUsage,
  getExceptions,
  getPartners,
  type AiUsage,
  type ActivityRecord,
  type ExceptionRecord,
  type Partner,
} from "../api";
import { ErrorPanel, Loading, EmptyState } from "../components/ScreenState";

export function OverviewScreen({
  onNavigate,
  onReview,
}: {
  onNavigate: (screen: string) => void;
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  void onReview;
  const [activity, setActivity] = useState<ActivityRecord[]>([]);
  const [exceptions, setExceptions] = useState<ExceptionRecord[]>([]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextActivity, nextExceptions, nextPartners, nextUsage] =
        await Promise.all([
          getActivity(),
          getExceptions(),
          getPartners(),
          getAiUsage(),
        ]);
      setActivity(nextActivity);
      setExceptions(nextExceptions);
      setPartners(nextPartners);
      setUsage(nextUsage);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const filtered = useMemo(
    () =>
      filter === "all"
        ? activity
        : activity.filter((item) => item.status === filter),
    [activity, filter],
  );
  const processed = activity.filter(
    (item) => item.status === "processed" && item.processed_at.startsWith(new Date().toISOString().slice(0, 10)),
  ).length;
  const openExceptions = exceptions.filter(
    (item) => item.status === "open",
  ).length;
  const activeMappings = partners.filter(
    (item) => item.version !== null,
  ).length;
  const success = activity.length
    ? Math.round((processed / activity.length) * 100)
    : 0;
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading pipeline activity..." />
      </div>
    );
  if (error)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );
  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">{new Date().toLocaleDateString()}</div>
          <h1>Pipeline overview</h1>
        </div>
        <button
          className="primary-button"
          onClick={() => onNavigate("Onboard")}
        >
          Onboard partner
        </button>
      </section>
      <section className="metric-grid">
        <Metric label="Processed" value={String(processed)} />
        <Metric label="Success rate" value={`${success}%`} />
        <Metric label="Open exceptions" value={String(openExceptions)} />
        <Metric label="Active mappings" value={String(activeMappings)} />
      </section>
      {usage && <CostPanel usage={usage} />}
      <section className="content-grid">
        <article className="panel">
          <h2>Mapping approvals</h2>
          {partners
            .filter((item) => item.pending_drafts > 0)
            .map((item) => (
              <button
                className="mapping-list-row"
                key={item.ats}
                onClick={() => onNavigate("Mappings")}
              >
                <strong>{item.ats}</strong>
                <span>{item.pending_drafts} pending draft(s)</span>
                <em>Review</em>
              </button>
            ))}
          {!partners.some((item) => item.pending_drafts > 0) && (
            <EmptyState label="No mappings are awaiting approval." />
          )}
        </article>
        <article className="panel">
          <h2>Connection status</h2>
          {partners.map((item) => (
            <div
              className="mapping-list-row"
              key={`${item.ats}-${item.payload_type}`}
            >
              <strong>{item.ats}</strong>
              <span>
                {item.payload_type} · {item.status}
              </span>
              <em>v{item.version ?? "-"}</em>
            </div>
          ))}
        </article>
      </section>
      <section className="panel activity-section">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">Live feed</span>
            <h2>Recent activity</h2>
          </div>
          <div className="filter-group">
            {["all", "processed", "exception", "needs_mapping"].map((item) => (
              <button
                key={item}
                className={filter === item ? "filter-active" : ""}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        {filtered.length ? (
          filtered.map((item) => (
            <div className="mapping-list-row" key={item.id}>
              <strong>{item.ats}</strong>
              <span>
                {item.payload_type} · {item.status}
              </span>
              <em>
                v{item.mapping_version ?? "-"} · {item.issue_count} issue(s)
              </em>
            </div>
          ))
        ) : (
          <EmptyState label="No activity matches this filter." />
        )}
      </section>
    </div>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <div className="metric-foot">
        <span>{label === "Processed" ? "All time" : "Current"}</span>
      </div>
    </article>
  );
}

function CostPanel({ usage }: { usage: AiUsage }) {
  const perOrder = usage.orders_processed
    ? (usage.calls / usage.orders_processed).toFixed(2)
    : "0.00";
  return (
    <section className="cost-panel">
      <div className="cost-headline">
        <strong>{usage.calls}</strong>
        <span>
          AI call{usage.calls === 1 ? "" : "s"} total, across{" "}
          {usage.partners_onboarded} partner
          {usage.partners_onboarded === 1 ? "" : "s"} - and{" "}
          <strong>{perOrder}</strong> per order across {usage.orders_processed}{" "}
          order{usage.orders_processed === 1 ? "" : "s"} processed.
        </span>
      </div>
      <div className="cost-figures">
        <div>
          <span>Input tokens</span>
          <strong>{usage.input_tokens.toLocaleString()}</strong>
        </div>
        <div>
          <span>Output tokens</span>
          <strong>{usage.output_tokens.toLocaleString()}</strong>
        </div>
        <div>
          <span>Model</span>
          <strong>{usage.recent[0]?.model ?? "not called yet"}</strong>
        </div>
      </div>
    </section>
  );
}
