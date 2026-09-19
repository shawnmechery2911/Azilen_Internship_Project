import { useEffect, useMemo, useState } from "react";
import {
  approveMapping,
  getDestinationFields,
  getFixtures,
  getReplay,
  getVersions,
  type FixturePayload,
  type MappingVersion,
  type ReplayResult,
} from "../api";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";

/** Static:1.0 is storage syntax; a reviewer should see a constant. */
function describeSource(source: string): { text: string; constant: boolean } {
  return source.startsWith("Static:")
    ? { text: source.slice("Static:".length), constant: true }
    : { text: source, constant: false };
}

/** Pull an example value out of a stored payload so a rule reads concretely. */
function valueAt(data: unknown, path: string): string | null {
  if (path.startsWith("Static:")) return path.slice("Static:".length);
  let node: unknown = data;
  for (const part of path.split(".")) {
    if (Array.isArray(node)) node = node[0];
    if (node === null || typeof node !== "object") return null;
    node = (node as Record<string, unknown>)[part];
  }
  if (Array.isArray(node)) node = node[0];
  if (node === null || node === undefined || typeof node === "object")
    return null;
  return String(node);
}

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
  const [destinations, setDestinations] = useState<string[]>([]);
  const [fixtures, setFixtures] = useState<FixturePayload[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [versions, nextReplay, nextDest, nextFixtures] = await Promise.all([
        getVersions(ats, payloadType),
        getReplay(ats, payloadType, version),
        getDestinationFields(),
        getFixtures(),
      ]);
      setMapping(versions.find((item) => item.version === version) ?? null);
      setReplay(nextReplay);
      setDestinations(nextDest);
      setFixtures(nextFixtures);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    }
  }
  useEffect(() => {
    void load();
  }, [ats, payloadType, version]);

  const sample = useMemo(
    () => fixtures.find((item) => item.ats === ats)?.data ?? null,
    [fixtures, ats],
  );

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

  const checked = replay?.checked ?? 0;
  const failing = [...new Set(replay?.results.flatMap((r) => r.issues) ?? [])];
  const alreadyApproved = mapping.status === "approved";
  // A partner with no stored orders yet has nothing to replay against. That is
  // every first mapping, so it cannot block approval - it only means the
  // guardrail has nothing to say, which the verdict states plainly.
  const blocked = failing.length > 0;

  const verdict = alreadyApproved
    ? { tone: "safe", head: "Approved", detail: `by ${mapping.approved_by ?? "a reviewer"}` }
    : failing.length
      ? {
          tone: "blocked",
          head: "Blocked by replay",
          detail: `${failing.join(", ")} breaks on ${checked} stored order${checked === 1 ? "" : "s"}`,
        }
      : checked === 0
        ? {
            tone: "unknown",
            head: "Nothing to replay against",
            detail:
              "This partner has no stored orders yet. You can approve, but replay is not guarding this one.",
          }
        : {
            tone: "safe",
            head: "Safe to approve",
            detail: `${checked} stored order${checked === 1 ? "" : "s"} still map cleanly`,
          };

  const blockedReason = alreadyApproved
    ? "This version is already approved"
    : blocked
      ? "Replay has to pass before this can be approved"
      : !reviewer.trim()
        ? "Enter your name to approve"
        : reviewer.trim() === mapping.proposed_by
          ? "The proposer cannot approve their own mapping"
          : "";

  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <button className="back-link" onClick={onDone}>
            <span aria-hidden="true">‹</span> Back to overview
          </button>
          <h1>
            {ats} · v{version}
          </h1>
          <p>
            {payloadType} · proposed by {mapping.proposed_by}
          </p>
        </div>
      </section>

      {error && <div className="toast">{error}</div>}

      <section className={`verdict verdict-${verdict.tone}`}>
        <strong>{verdict.head}</strong>
        <span>{verdict.detail}</span>
      </section>

      <section className="coverage">
        <div>
          <strong>
            {mapping.mappings.length} of {destinations.length || "?"}
          </strong>
          <span>destination fields mapped</span>
        </div>
        <div>
          <strong>{mapping.abstentions.length}</strong>
          <span>the model declined to guess</span>
        </div>
        <div>
          <strong>
            {Math.max(
              0,
              destinations.length -
                mapping.mappings.length -
                mapping.abstentions.length,
            )}
          </strong>
          <span>not covered either way</span>
        </div>
        <div>
          <strong>{checked}</strong>
          <span>stored orders replayed</span>
        </div>
      </section>

      <section className="panel">
        <h2>Field mappings</h2>
        <div className="map-table">
          <div className="map-head">
            <span>{ats} sends</span>
            <span />
            <span>we store it as</span>
            <span>example</span>
          </div>
          {mapping.mappings.map((rule, index) => {
            const example = sample ? valueAt(sample, rule.source) : null;
            const source = describeSource(rule.source);
            const notes = [
              rule.transform ? `transform: ${rule.transform}` : null,
              rule.source_is_list ? "list" : null,
              rule.required ? "required" : null,
            ].filter(Boolean);
            return (
              <div className="map-line" key={`${rule.destination}-${index}`}>
                <span className="map-src">
                  <code>{source.text}</code>
                  {source.constant && <em className="map-const">constant</em>}
                </span>
                <span className="map-arrow" aria-hidden="true">
                  →
                </span>
                <code className="map-dest">{rule.destination}</code>
                <span className="map-sample">
                  {source.constant ? "" : (example ?? "—")}
                </span>
                {(rule.reason || notes.length > 0) && (
                  <span className="map-note">
                    {rule.reason}
                    {rule.reason && notes.length > 0 ? " · " : ""}
                    {notes.join(" · ")}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <div className="content-grid">
        <div className="panel">
          <h2>Not mapped</h2>
          {mapping.abstentions.length ? (
            mapping.abstentions.map((item, index) => (
              <div className="map-row" key={`${item.destination}-${index}`}>
                <code className="map-dest">{item.destination}</code>
                <span className="map-reason">{item.reason}</span>
              </div>
            ))
          ) : (
            <EmptyState label="The model mapped every destination field it was given." />
          )}
        </div>

        <div className="panel">
          <h2>Replay detail</h2>
          {checked ? (
            replay?.results.map((result) => (
              <div className="map-row" key={result.payload}>
                <div className="map-line-plain">
                  <code className="map-dest">{result.payload}</code>
                  <span
                    className={`status ${result.status === "processed" ? "status-processed" : "status-exception"}`}
                  >
                    {result.status}
                  </span>
                </div>
                {result.issues.length > 0 && (
                  <span className="map-reason">
                    fails on {result.issues.join(", ")}
                  </span>
                )}
              </div>
            ))
          ) : (
            <EmptyState label="No stored orders for this partner yet." />
          )}
        </div>
      </div>

      <section className="approve-bar">
        <div>
          <label htmlFor="reviewer">Approving as</label>
          <input
            id="reviewer"
            className="reviewer-input"
            placeholder="Your name"
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
            disabled={alreadyApproved}
          />
        </div>
        <div className="approve-action">
          {blockedReason && <span className="approve-reason">{blockedReason}</span>}
          <button
            className="primary-button"
            disabled={Boolean(blockedReason) || busy}
            onClick={() => void approve()}
          >
            {busy ? "Approving..." : "Approve mapping"}
          </button>
        </div>
      </section>
    </div>
  );
}
