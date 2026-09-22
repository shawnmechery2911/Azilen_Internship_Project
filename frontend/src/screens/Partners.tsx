import { useCallback, useEffect, useState } from "react";
import {
  getExceptions,
  getMapping,
  getPartnerSamples,
  getPartners,
  getVersions,
  type ExceptionRecord,
  type MappingVersion,
  type Partner,
  type PartnerSample,
} from "../api";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";
import { RulesScreen } from "./Rules";

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** Everything about one partner in one place. It was spread across four
 *  screens: the mapping on the overview, presence rules behind a scope tab on
 *  Validation, orders nowhere at all, and exceptions filtered by hand. */
function PartnerDetail({
  partner,
  onBack,
  onReview,
  onExceptions,
}: {
  partner: Partner;
  onBack: () => void;
  onReview: (ats: string, payloadType: string, version: number) => void;
  onExceptions: (ats: string) => void;
}) {
  const [versions, setVersions] = useState<MappingVersion[] | null>(null);
  const [mapping, setMapping] = useState<MappingVersion | null>(null);
  const [orders, setOrders] = useState<PartnerSample[]>([]);
  const [open, setOpen] = useState<ExceptionRecord[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextVersions, nextOrders, everyException] = await Promise.all([
        getVersions(partner.ats, partner.payload_type),
        getPartnerSamples(partner.ats).catch(() => []),
        getExceptions().catch(() => []),
      ]);
      setVersions(nextVersions);
      setOrders(nextOrders);
      setOpen(
        everyException.filter(
          (item) => item.ats === partner.ats && item.status === "open",
        ),
      );
      // a partner with no approved mapping has nothing to show here yet
      setMapping(
        await getMapping(partner.ats, partner.payload_type).catch(() => null),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this partner");
    } finally {
      setLoading(false);
    }
  }, [partner.ats, partner.payload_type]);
  useEffect(() => {
    void load();
  }, [load]);

  const mapped = mapping?.mappings.length ?? 0;
  const demanded = mapping?.mappings.filter((row) => row.required).length ?? 0;

  return (
    <div className="page-wrap">
      <button className="back-link" onClick={onBack}>
        <span aria-hidden="true">‹</span> All partners
      </button>

      <section className="page-heading">
        <div>
          <div className="eyebrow">Partner</div>
          <h1>{partner.ats}</h1>
          <p>
            Sends <strong>{partner.payload_type}</strong> orders
            {mapping ? (
              <>
                {" "}
                · mapping v{mapping.version} fills {plural(mapped, "field")},{" "}
                {demanded} of them always
              </>
            ) : (
              <> · no approved mapping yet</>
            )}
          </p>
        </div>
      </section>

      {error && <div className="toast">{error}</div>}
      {loading ? (
        <Loading label={`Loading ${partner.ats}...`} rows={4} />
      ) : (
        <>
          <section className="panel">
            <div className="panel-head-row">
              <h2>Mapping</h2>
              {open.length > 0 && (
                <button
                  className="link-button"
                  onClick={() => onExceptions(partner.ats)}
                >
                  {plural(open.length, "open exception")} ›
                </button>
              )}
            </div>
            {versions?.length ? (
              versions.map((version) => (
                <button
                  className="row"
                  key={version.version}
                  onClick={() =>
                    onReview(version.ats, version.payload_type, version.version)
                  }
                >
                  <span className="row-name">v{version.version}</span>
                  <span className="row-desc">
                    proposed by {version.proposed_by}
                    {version.approved_by ? `, approved by ${version.approved_by}` : ""}
                  </span>
                  <span className={`status status-${version.status}`}>
                    {version.status}
                  </span>
                  <em className="row-action">
                    Open review <span aria-hidden="true">›</span>
                  </em>
                </button>
              ))
            ) : (
              <EmptyState label="No mapping has been drafted for this partner." />
            )}
          </section>

          <section className="panel">
            <div className="panel-head-row">
              <h2>Stored orders</h2>
              <span className="status-pill">{orders.length} kept</span>
            </div>
            <p className="empty-note">
              What this partner has actually sent. A new mapping is replayed
              against every one of these before it can be approved.
            </p>
            {orders.map((order) => (
              <div className="row row-static" key={order.label}>
                <span className="row-name">{order.label}</span>
                <span className="row-desc">
                  {Object.keys(order.data).length} top-level fields
                </span>
              </div>
            ))}
          </section>

          <section className="panel">
            <div className="panel-head-row">
              <h2>What {partner.ats} must send</h2>
            </div>
            <RulesScreen scope={partner.ats} embedded />
          </section>
        </>
      )}
    </div>
  );
}

export function PartnersScreen({
  onReview,
  onExceptions,
}: {
  onReview: (ats: string, payloadType: string, version: number) => void;
  onExceptions: (ats: string) => void;
}) {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [chosen, setChosen] = useState<Partner | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPartners(await getPartners());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load partners");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (chosen)
    return (
      <PartnerDetail
        partner={chosen}
        onBack={() => setChosen(null)}
        onReview={onReview}
        onExceptions={onExceptions}
      />
    );
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading partners..." rows={3} />
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
          <div className="eyebrow">Configuration</div>
          <h1>Partners</h1>
          <p>
            Every ATS that has been onboarded. Open one to see its mapping, the
            orders it has sent, and what it is held to.
          </p>
        </div>
      </section>

      <section className="panel">
        {partners.length === 0 ? (
          <EmptyState label="No partners onboarded yet." />
        ) : (
          partners.map((partner) => (
            <button
              className="row"
              key={`${partner.ats}-${partner.payload_type}`}
              onClick={() => setChosen(partner)}
            >
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
                Open <span aria-hidden="true">›</span>
              </em>
            </button>
          ))
        )}
      </section>
    </div>
  );
}
