import { useEffect, useState } from "react";
import {
  getPartners,
  getVersions,
  type MappingVersion,
  type Partner,
} from "../api";
import { ErrorPanel, Loading, EmptyState } from "../components/ScreenState";

export function MappingsScreen({
  onReview,
}: {
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [versions, setVersions] = useState<MappingVersion[]>([]);
  const [selected, setSelected] = useState<Partner | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    setLoading(true);
    setError("");
    try {
      setPartners(await getPartners());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function select(partner: Partner) {
    setSelected(partner);
    try {
      setVersions(await getVersions(partner.ats, partner.payload_type));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading mappings..." />
      </div>
    );
  if (error)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );
  if (!partners.length)
    return (
      <div className="page-wrap">
        <EmptyState label="No partners have been seeded yet." />
      </div>
    );
  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Configuration</div>
          <h1>Mappings</h1>
          <p>Review every version before it reaches production.</p>
        </div>
      </section>
      <div className="content-grid">
        <div className="panel">
          <h2>Partners</h2>
          {partners.map((partner) => (
            <button
              className="mapping-list-row"
              key={`${partner.ats}-${partner.payload_type}`}
              onClick={() => void select(partner)}
            >
              <strong>{partner.ats}</strong>
              <span>
                {partner.payload_type} · v{partner.version ?? "-"}
              </span>
              <em>{partner.pending_drafts} draft(s)</em>
            </button>
          ))}
        </div>
        <div className="panel">
          <h2>{selected ? `${selected.ats} versions` : "Select a partner"}</h2>
          {selected &&
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
            ))}
        </div>
      </div>
    </div>
  );
}
