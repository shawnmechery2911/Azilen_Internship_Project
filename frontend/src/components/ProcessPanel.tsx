import { useEffect, useMemo, useState } from "react";
import {
  draftMapping,
  getMapping,
  getPartners,
  getPartnerSamples,
  remapSource,
  runProcess,
  type Partner,
  type PartnerSample,
  type ProcessResult,
} from "../api";
import { ErrorPanel } from "./ScreenState";
import { IssueList } from "./IssueList";
import { PayloadView } from "./PayloadView";

/** What a partner plausibly renames a field to. A believable rename matters:
 *  the point is to show drift spotting a real change, not a scrambled key. */
const RENAMES: [RegExp, string][] = [
  [/ApplicantID$/i, "CandidateID"],
  [/CandidateID$/i, "ApplicantRef"],
  [/^Email$/i, "EmailAddress"],
  [/FirstName$/i, "GivenName"],
  [/LastName$/i, "Surname"],
  [/ID$/i, "Ref"],
  [/^Username$/i, "UserLogin"],
  [/^AccountNumber$/i, "AccountNo"],
  [/^Package$/i, "PackageName"],
];

function renamedKey(key: string): string {
  for (const [pattern, replacement] of RENAMES) {
    if (pattern.test(key)) return key.replace(pattern, replacement);
  }
  return `${key}Value`;
}

function readPath(payload: Record<string, unknown>, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        node && typeof node === "object"
          ? (node as Record<string, unknown>)[part]
          : undefined,
      payload,
    );
}

/** Change the payload the way a partner would, on a path the mapping reads -
 *  otherwise nothing downstream notices and the demo shows nothing. */
function alter(
  payload: Record<string, unknown>,
  sources: { source: string; required: boolean }[],
  how: "drop" | "rename",
): { data: Record<string, unknown>; field: string } {
  const copy: Record<string, unknown> = JSON.parse(JSON.stringify(payload));
  const usable = sources.filter(
    (row) =>
      !row.source.startsWith("Static:") &&
      readPath(copy, row.source) !== undefined,
  );
  // a required field first: changing one the mapping does not depend on
  // proves drift fires on a clean order, but it is the weaker story
  const target = (usable.find((row) => row.required) ?? usable[0])?.source;
  if (!target) return { data: copy, field: "" };

  const parts = target.split(".");
  const key = parts.pop() as string;
  const parent = parts.reduce<Record<string, unknown>>(
    (node, part) => node[part] as Record<string, unknown>,
    copy,
  );
  if (how === "drop") {
    delete parent[key];
    return { data: copy, field: target };
  }
  parent[renamedKey(key)] = parent[key];
  delete parent[key];
  return { data: copy, field: `${target} -> ${renamedKey(key)}` };
}

export function ProcessPanel({
  onReview,
}: {
  onReview: (
    ats: string,
    payloadType: string,
    version: number,
    retired?: number,
  ) => void;
}) {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [ats, setAts] = useState("");
  const [samples, setSamples] = useState<PartnerSample[]>([]);
  const [chosen, setChosen] = useState("");
  const [how, setHow] = useState<"as-is" | "drop" | "rename">("as-is");
  const [sources, setSources] = useState<
    { source: string; required: boolean }[]
  >([]);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void getPartners()
      .then((found) => {
        // only a partner with an approved mapping can be sent an order
        const usable = found.filter((item) => item.version !== null);
        setPartners(usable);
        setAts((current) => current || usable[0]?.ats || "");
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load partners"),
      );
  }, []);

  useEffect(() => {
    if (!ats) return;
    setResult(null);
    void getPartnerSamples(ats)
      .then((found) => {
        setSamples(found);
        setChosen(found[0]?.label ?? "");
      })
      .catch(() => setSamples([]));
    const partnerType = partners.find((item) => item.ats === ats)?.payload_type;
    if (partnerType) {
      void getMapping(ats, partnerType)
        .then((m) =>
          setSources(
            m.mappings.map((row) => ({
              source: row.source,
              required: row.required,
            })),
          ),
        )
        .catch(() => setSources([]));
    }
  }, [ats, partners]);

  const partner = useMemo(
    () => partners.find((item) => item.ats === ats),
    [partners, ats],
  );
  const sample = samples.find((item) => item.label === chosen);

  async function run() {
    if (!partner || !sample) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await runProcess({
          ats: partner.ats,
          payload_type: partner.payload_type,
          data:
            how === "as-is" ? sample.data : alter(sample.data, sources, how).data,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  /** Drift already worked out what the field became, so acting on it is a
   *  substitution rather than another question for the model. */
  async function remap(from: string, to: string) {
    if (!partner) return;
    setBusy(true);
    setError("");
    try {
      const { version, retired_samples } = await remapSource(
        partner.ats,
        partner.payload_type,
        from,
        to,
      );
      onReview(partner.ats, partner.payload_type, version, retired_samples);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remap that field");
    } finally {
      setBusy(false);
    }
  }

  async function requestRepair() {
    if (!partner || !sample) return;
    setBusy(true);
    setError("");
    try {
      const current = await getMapping(partner.ats, partner.payload_type);
      const draft = await draftMapping(
        partner.ats,
        partner.payload_type,
        how === "as-is" ? sample.data : alter(sample.data, sources, how).data,
        current.mappings.map((item) => item.destination),
      );
      onReview(partner.ats, partner.payload_type, draft.version);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not request a mapping",
      );
    } finally {
      setBusy(false);
    }
  }

  if (error && !partners.length)
    return <ErrorPanel message={error} retry={() => window.location.reload()} />;

  return (
    <section className="panel process-panel">
      <div className="panel-head-row">
        <h2>Send a test order</h2>
        <span className="status-pill">No model call</span>
      </div>

      {partners.length === 0 ? (
        <p className="empty-note">
          No partner has an approved mapping yet, so there is nothing to send an
          order to.
        </p>
      ) : (
        <>
          <div className="process-controls">
            <label className="sr-only" htmlFor="test-partner">
              Partner
            </label>
            <select
              id="test-partner"
              value={ats}
              onChange={(event) => setAts(event.target.value)}
            >
              {partners.map((item) => (
                <option key={item.ats} value={item.ats}>
                  {item.ats}
                </option>
              ))}
            </select>

            <label className="sr-only" htmlFor="test-payload">
              Order
            </label>
            <select
              id="test-payload"
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
              disabled={!samples.length}
            >
              {samples.length ? (
                samples.map((item) => (
                  <option key={item.label} value={item.label}>
                    {item.label}
                  </option>
                ))
              ) : (
                <option value="">no stored orders yet</option>
              )}
            </select>

            <label className="sr-only" htmlFor="test-how">
              How to send it
            </label>
            <select
              id="test-how"
              value={how}
              onChange={(event) =>
                setHow(event.target.value as "as-is" | "drop" | "rename")
              }
            >
              <option value="as-is">send as-is</option>
              <option value="drop">drop a field</option>
              <option value="rename">rename a field</option>
            </select>

            <button
              className="primary-button"
              disabled={busy || !sample}
              onClick={() => void run()}
            >
              {busy ? "Running..." : "Run payload"}
            </button>
          </div>

          {!samples.length && (
            <p className="empty-note">
              Nothing from {ats} has been kept yet, so there is no order to
              replay.
            </p>
          )}
          {error && <div className="toast">{error}</div>}

          {result && (
            <div className="process-result">
              <div className={`banner banner-${result.status}`}>
                <strong>
                  {result.status === "processed" ? "Processed" : "Exception"}
                </strong>
                <span>
                  mapping v{result.mapping_version ?? "none"} ·{" "}
                  {result.issues.length} issue
                  {result.issues.length === 1 ? "" : "s"} ·{" "}
                  <strong>0 AI calls</strong>
                </span>
              </div>
              {result.issues.length > 0 && <IssueList issues={result.issues} />}
              {result.drift_alerts.length > 0 && (
                <div className="drift-list">
                  {result.drift_alerts.map((alert, index) => (
                    <div
                      className={`drift drift-${alert.kind ?? "changed"}`}
                      key={`${alert.field}-${index}`}
                    >
                      <span className="drift-kind">
                        {alert.kind ?? "changed"}
                      </span>
                      <span className="drift-message">{alert.message}</span>
                      {alert.kind === "renamed" && alert.became ? (
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void remap(alert.field, alert.became!)}
                        >
                          Remap to {alert.became}
                        </button>
                      ) : (
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void requestRepair()}
                        >
                          Ask for a new mapping
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {result && sample && (
            <PayloadView
              sample={{ ats, label: chosen, data: sample.data }}
              result={result}
            />
          )}
        </>
      )}
    </section>
  );
}
