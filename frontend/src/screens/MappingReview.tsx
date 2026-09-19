import { useEffect, useState } from "react";
import {
  approveMapping,
  getReplay,
  getVersions,
  type MappingVersion,
  type ReplayResult,
} from "../api";
import { ErrorPanel, Loading } from "../components/ScreenState";

export function MappingReviewScreen({
  ats,
  payloadType,
  version,
  onDone,
}: {
  ats: string;
  payloadType: string;
  version: number;
  onDone: () => void;
}) {
  const [mapping, setMapping] = useState<MappingVersion | null>(null);
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      const versions = await getVersions(ats, payloadType);
      setMapping(versions.find((item) => item.version === version) ?? null);
      setReplay(await getReplay(ats, payloadType, version));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }
  useEffect(() => {
    void load();
  }, [ats, payloadType, version]);
  async function approve() {
    setBusy(true);
    setError("");
    try {
      await approveMapping(ats, payloadType, version, reviewer);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setBusy(false);
    }
  }
  if (error && !mapping)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );
  if (!mapping)
    return (
      <div className="page-wrap">
        <Loading label="Loading mapping review..." />
      </div>
    );
  const safe = replay?.safe ?? false;
  const failingFields = replay?.results.flatMap((item) => item.issues) ?? [];
  const replayMessage = !safe
    ? `Blocked - this version breaks ${failingFields.length} field${failingFields.length === 1 ? "" : "s"}`
    : replay?.checked === 0
      ? "Nothing to replay against yet"
      : `Safe to approve - ${replay?.checked ?? 0} stored order${replay?.checked === 1 ? "" : "s"} still map cleanly`;
  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Mapping review</div>
          <h1>
            {ats} / {payloadType} / v{version}
          </h1>
          <p>Proposed by {mapping.proposed_by}</p>
        </div>
      </section>
      {error && <div className="toast">{error}</div>}
      <div className="content-grid">
        <div className="panel">
          <h2>Rules</h2>
          {mapping.mappings.map((rule, index) => (
            <div className="mapping-rule" key={`${rule.destination}-${index}`}>
              <strong>
                {rule.source} → {rule.destination}
              </strong>
              <span>
                {rule.transform ?? "identity"} ·{" "}
                {rule.required ? "required" : "optional"} ·{" "}
                {rule.source_is_list ? "list" : "single"}
              </span>
            </div>
          ))}
          {mapping.abstentions.map((item, index) => (
            <div className="mapping-rule abstention" key={`${item.destination}-${index}`}>
              <strong>Not mapped - AI abstained: {item.destination}</strong>
              <span>{item.reason}</span>
            </div>
          ))}
        </div>
        <div className="panel">
          <h2>Replay check</h2>
          {replay?.results.map((result) => (
            <div className="mapping-rule" key={result.payload}>
              <strong>
                {result.payload}: {result.status}
              </strong>
              <span>
                {result.issues.length
                  ? `Failing fields: ${result.issues.join(", ")}`
                  : "All fields passed"}
              </span>
            </div>
          ))}
          <p
            className={
              safe && replay?.checked ? "success-text" : "warning-text"
            }
          >
            {replayMessage}
          </p>
          <input
            className="reviewer-input"
            placeholder="Reviewer name"
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
          />
          <button
            className="primary-button"
            disabled={!safe || !reviewer.trim() || busy}
            onClick={() => void approve()}
          >
            {busy ? "Approving..." : "Approve mapping"}
          </button>
        </div>
      </div>
    </div>
  );
}
