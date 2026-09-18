import { useEffect, useState } from "react";
import {
  draftMapping,
  getFixtures,
  getMapping,
  runProcess,
  type FixturePayload,
  type ProcessResult,
} from "../api";
import { ErrorPanel, Loading } from "./ScreenState";
import { PayloadView } from "./PayloadView";
import { IssueList } from "./IssueList";

export function ProcessPanel({
  onReview,
}: {
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [fixtures, setFixtures] = useState<FixturePayload[]>([]);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const next = await getFixtures();
      setFixtures(next);
      setSelected(next[0]?.name ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fixtures");
    }
  }

  useEffect(() => {
    void load();
  }, []);
  const fixture = fixtures.find((item) => item.name === selected);

  async function run() {
    if (!fixture) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await runProcess({
          ats: fixture.ats,
          payload_type: fixture.payload_type,
          data: fixture.data,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  async function requestRepair() {
    if (!fixture) return;
    setBusy(true);
    setError("");
    try {
      const current = await getMapping(fixture.ats, fixture.payload_type);
      const draft = await draftMapping(
        fixture.ats,
        fixture.payload_type,
        fixture.data,
        current.mappings.map((item) => item.destination),
      );
      onReview(fixture.ats, fixture.payload_type, draft.version);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not request mapping",
      );
    } finally {
      setBusy(false);
    }
  }

  if (error && !fixtures.length)
    return <ErrorPanel message={error} retry={() => void load()} />;
  if (!fixtures.length)
    return <Loading label="Loading stored demo payloads..." />;
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Deterministic runtime</span>
          <h2>Run an order</h2>
        </div>
        <span className="status-pill">
          {result ? (result.status === "processed" ? "Processed" : "Exception") : "No model call"}
        </span>
      </div>
      <div className="process-controls">
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          {fixtures.map((item) => (
            <option key={item.name}>{item.name}</option>
          ))}
        </select>
        <button
          className="primary-button"
          disabled={busy}
          onClick={() => void run()}
        >
          {busy ? "Processing..." : "Run payload"}
        </button>
      </div>
      {error && <div className="toast">{error}</div>}
      {result && (
        <div className="process-result">
          <div className={`result-banner result-${result.status}`}>
            <strong>{result.status === "processed" ? "Processed" : "Exception"}</strong>
            <span>
              mapping v{result.mapping_version ?? "none"} · {result.issues.length} issue
              {result.issues.length === 1 ? "" : "s"} · 0 AI calls
            </span>
          </div>
          {result.issues.length > 0 && <IssueList issues={result.issues} />}
          {result.drift_alerts.length > 0 && (
            <div className="warning-text">
              Drift alert: repeated failures detected.{" "}
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => void requestRepair()}
              >
                Request updated mapping
              </button>
            </div>
          )}
        </div>
      )}
      {result && fixture && (
        <PayloadView
          sample={{ ats: fixture.ats, label: fixture.name, data: fixture.data }}
          result={result}
        />
      )}
    </section>
  );
}
