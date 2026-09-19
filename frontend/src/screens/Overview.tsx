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
  onNavigate: (screen: string) => void;
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [activity, setActivity] = useState<ActivityRecord[]>([]);
  const [exceptions, setExceptions] = useState<ExceptionRecord[]>([]);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const [versions, setVersions] = useState<MappingVersion[]>([]);
  const [selected, setSelected] = useState<Partner | null>(null);
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

  async function openPartner(partner: Partner) {
    setSelected(partner);
    try {
      setVersions(await getVersions(partner.ats, partner.payload_type));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }

  const filtered = useMemo(
    () =>
      filter === "all"
        ? activity
        : activity.filter((item) => item.status === filter),
    [activity, filter],
  );

  /** Only things somebody has to act on, each carrying the action itself. */
  const attention = useMemo<Attention[]>(() => {
    const items: Attention[] = [];
    for (const partner of partners) {
      if (partner.pending_drafts > 0) {
        items.push({
          key: `draft-${partner.ats}`,
          ats: partner.ats,
          what: `${partner.pending_drafts} mapping draft${partner.pending_drafts === 1 ? "" : "s"} awaiting approval`,
          action: "Review",
          run: () => void openPartner(partner),
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
        what: `${count} open exception${count === 1 ? "" : "s"}`,
        action: "Open queue",
        run: () => onNavigate("Exceptions"),
      });
    }
    return items;
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

      <section className="panel">
        <h2>Needs attention</h2>
        {attention.length ? (
          attention.map((item) => (
            <button
              className="mapping-list-row"
              key={item.key}
              onClick={item.run}
            >
              <strong>{item.ats}</strong>
              <span>{item.what}</span>
              <em>{item.action}</em>
            </button>
          ))
        ) : (
          <EmptyState label="Nothing needs attention. Every partner is mapped and processing." />
        )}
      </section>

      <div className="content-grid">
        <div className="panel">
          <h2>Partners</h2>
          {partners.map((partner) => (
            <button
              className="mapping-list-row"
              key={`${partner.ats}-${partner.payload_type}`}
              onClick={() => void openPartner(partner)}
            >
              <strong>{partner.ats}</strong>
              <span>
                {partner.payload_type} ·{" "}
                {partner.version === null
                  ? "needs mapping"
                  : `v${partner.version} ${partner.status}`}
              </span>
              <em>
                {partner.pending_drafts > 0
                  ? `${partner.pending_drafts} draft(s)`
                  : "History"}
              </em>
            </button>
          ))}
        </div>
        <div className="panel">
          <h2>{selected ? `${selected.ats} versions` : "Select a partner"}</h2>
          {selected ? (
            versions.map((version) => (
              <button
                className="mapping-list-row"
                key={version.version}
                onClick={() =>
                  onReview(version.ats, version.payload_type, version.version)
                }
              >
                <strong>Version {version.version}</strong>
                <span>
                  {version.status} · proposed by {version.proposed_by}
                </span>
                <em>Open review</em>
              </button>
            ))
          ) : (
            <EmptyState label="Pick a partner to see its mapping versions." />
          )}
        </div>
      </div>

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
                {item.replace("_", " ")}
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
