import { useEffect, useMemo, useState } from "react";
import {
  getActivity,
  getAiUsage,
  getExceptions,
  getPartners,
  getVersions,
  type AiUsage,
  type ActivityRecord,
  type ExceptionRecord,
  type MappingVersion,
  type Partner,
} from "../api";
import { ErrorPanel, Loading, EmptyState } from "../components/ScreenState";

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** A feed without times is just a list, so every row gets one. */
function since(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

type Attention = {
  key: string;
  ats: string;
  what: string;
  action: string;
  run: () => void;
};

export function OverviewScreen({
  onNavigate,
  onReview,
}: {
  onNavigate: (screen: string, ats?: string) => void;
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [activity, setActivity] = useState<ActivityRecord[]>([]);
  const [exceptions, setExceptions] = useState<ExceptionRecord[]>([]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [versions, setVersions] = useState<Record<string, MappingVersion[]>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
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

  /** Versions open under the partner row itself, so nothing sits empty. */
  async function togglePartner(partner: Partner) {
    const key = `${partner.ats}-${partner.payload_type}`;
    if (expanded === key) {
      setExpanded(null);
      return;
    }
    setExpanded(key);
    if (!versions[key]) {
      try {
        const found = await getVersions(partner.ats, partner.payload_type);
        setVersions((current) => ({ ...current, [key]: found }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Request failed");
      }
    }
  }

  const filtered = useMemo(
    () =>
      filter === "all"
        ? activity
        : activity.filter((item) => item.status === filter),
    [activity, filter],
  );

  const attention = useMemo<Attention[]>(() => {
    const items: Attention[] = [];
    for (const partner of partners) {
      if (partner.pending_drafts > 0) {
        items.push({
          key: `draft-${partner.ats}`,
          ats: partner.ats,
          what: `${plural(partner.pending_drafts, "mapping draft")} awaiting approval`,
          action: "Review",
          run: () => void togglePartner(partner),
        });
      } else if (partner.version === null) {
        items.push({
          key: `unmapped-${partner.ats}`,
          ats: partner.ats,
          what: "No approved mapping yet",
          action: "Onboard",
          run: () => onNavigate("Onboard"),
        });
      }
    }
    const open = exceptions.filter((item) => item.status === "open");
    for (const ats of new Set(open.map((item) => item.ats))) {
      const count = open.filter((item) => item.ats === ats).length;
      items.push({
        key: `exc-${ats}`,
        ats,
        what: plural(count, "open exception"),
        action: "Open queue",
        run: () => onNavigate("Exceptions", ats),
      });
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partners, exceptions, onNavigate]);

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
          <h1>Pipeline overview</h1>
        </div>
        <button className="primary-button" onClick={() => onNavigate("Onboard")}>
          Onboard partner
        </button>
      </section>

      <section className="panel">
        <h2>Needs attention</h2>
        {attention.length ? (
          attention.map((item) => (
            <button className="row" key={item.key} onClick={item.run}>
              <span className="row-name">{item.ats}</span>
              <span className="row-desc">{item.what}</span>
              <em className="row-action">
                {item.action}
                <span aria-hidden="true">›</span>
              </em>
            </button>
          ))
        ) : (
          <EmptyState label="Nothing needs attention. Every partner is mapped and processing." />
        )}
      </section>

      <section className="panel">
        <h2>Partners</h2>
        {partners.map((partner) => {
          const key = `${partner.ats}-${partner.payload_type}`;
          const isOpen = expanded === key;
          const rows = versions[key];
          return (
            <div key={key}>
              <button className="row row-partner" onClick={() => void togglePartner(partner)}>
                <span className="row-name">{partner.ats}</span>
                <span className="row-desc">{partner.payload_type}</span>
                {partner.pending_drafts > 0 ? (
                  <span className="row-badge">
                    {plural(partner.pending_drafts, "draft")}
                  </span>
                ) : (
                  <span className="row-cell-empty" />
                )}
                <span className={`status status-${partner.status}`}>
                  {partner.status.replace("_", " ")}
                </span>
                <code className="row-meta">
                  {partner.version === null ? "—" : `v${partner.version}`}
                </code>
                <em className="row-action">
                  {isOpen ? "Hide" : "Versions"}
                  <span aria-hidden="true">{isOpen ? "⌃" : "⌄"}</span>
                </em>
              </button>
              {isOpen && (
                <div className="row-expand">
                  {rows ? (
                    rows.map((version) => (
                      <button
                        className="row row-nested"
                        key={version.version}
                        onClick={() =>
                          onReview(
                            version.ats,
                            version.payload_type,
                            version.version,
                          )
                        }
                      >
                        <span className="row-name">v{version.version}</span>
                        <span className="row-desc">
                          proposed by {version.proposed_by}
                        </span>
                        <span className={`status status-${version.status}`}>
                          {version.status}
                        </span>
                        <em className="row-action">
                          Open review
                          <span aria-hidden="true">›</span>
                        </em>
                      </button>
                    ))
                  ) : (
                    <EmptyState label="Loading versions..." />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </section>

      <section className="panel">
        <h2>Recent activity</h2>
        <div className="filter-group filter-row">
          {["all", "processed", "exception", "needs_mapping"].map((item) => (
            <button
              key={item}
              className={filter === item ? "filter-active" : ""}
              onClick={() => setFilter(item)}
            >
              {item.replace("_", " ")}
            </button>
          ))}
        </div>
        {filtered.length ? (
          filtered.map((item) => (
            <div className="row row-activity" key={item.id}>
              <span className="row-name">{item.ats}</span>
              <span className="row-desc">{item.payload_type}</span>
              <span className={`status status-${item.status}`}>
                {item.status.replace("_", " ")}
              </span>
              <code className="row-meta">
                v{item.mapping_version ?? "—"} ·{" "}
                {plural(item.issue_count, "issue")}
              </code>
              <span className="row-time">{since(item.processed_at)}</span>
            </div>
          ))
        ) : (
          <EmptyState label="No activity matches this filter." />
        )}
      </section>

      {usage && <CostPanel usage={usage} />}
    </div>
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
