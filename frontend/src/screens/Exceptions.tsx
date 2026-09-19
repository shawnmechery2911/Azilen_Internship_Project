import { useEffect, useMemo, useState } from "react";
import {
  assignException,
  closeException,
  getExceptions,
  type ExceptionRecord,
} from "../api";
import { ErrorPanel, Loading, EmptyState } from "../components/ScreenState";
import { IssueList } from "../components/IssueList";

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

export function ExceptionsScreen({ ats }: { ats?: string | null }) {
  const [records, setRecords] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [owners, setOwners] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [state, setState] = useState<"open" | "closed" | "all">("open");
  const [payloadOpen, setPayloadOpen] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setRecords(await getExceptions());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function act(id: string, action: () => Promise<ExceptionRecord>) {
    setBusy(id);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy("");
    }
  }

  const forPartner = useMemo(
    () => (ats && !showAll ? records.filter((r) => r.ats === ats) : records),
    [records, ats, showAll],
  );
  const counts = useMemo(
    () => ({
      open: forPartner.filter((r) => r.status === "open").length,
      closed: forPartner.filter((r) => r.status === "closed").length,
      all: forPartner.length,
    }),
    [forPartner],
  );
  const visible = useMemo(
    () => (state === "all" ? forPartner : forPartner.filter((r) => r.status === state)),
    [forPartner, state],
  );

  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading exceptions..." rows={3} />
      </div>
    );
  if (error && !records.length)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );

  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Operations</div>
          <h1>Exception queue</h1>
        </div>
      </section>

      {ats && !showAll && (
        <div className="filter-note">
          <span>
            Showing <strong>{ats}</strong> only
          </span>
          <button className="link-button" onClick={() => setShowAll(true)}>
            Show every partner
          </button>
        </div>
      )}
      {error && <div className="toast">{error}</div>}

      <div className="filter-group filter-row">
        {(["open", "closed", "all"] as const).map((option) => (
          <button
            key={option}
            className={state === option ? "filter-active" : ""}
            onClick={() => setState(option)}
          >
            {option} ({counts[option]})
          </button>
        ))}
      </div>

      {visible.length ? (
        <div className="exception-list">
          {visible.map((record) => (
            <article className="exception-card" key={record.id}>
              <header className="exception-head">
                <strong>{record.ats}</strong>
                <span className="exception-type">{record.payload_type}</span>
                <span
                  className={`status ${record.status === "open" ? "status-exception" : "status-processed"}`}
                >
                  {record.status}
                </span>
                <span className="exception-spacer" />
                <code className="row-meta">v{record.mapping_version ?? "-"}</code>
                <span className="row-time">{since(record.created_at)}</span>
              </header>

              <IssueList issues={record.issues} />

              <footer className="exception-foot">
                <span className="exception-owner">
                  {record.owner ? (
                    <>
                      Owned by <strong>{record.owner}</strong>
                    </>
                  ) : (
                    "Unassigned"
                  )}
                </span>

                {record.status === "open" && (
                  <div className="exception-actions">
                    <label className="sr-only" htmlFor={`owner-${record.id}`}>
                      Owner name
                    </label>
                    <input
                      id={`owner-${record.id}`}
                      placeholder="Owner name"
                      value={owners[record.id] ?? ""}
                      onChange={(event) =>
                        setOwners((current) => ({
                          ...current,
                          [record.id]: event.target.value,
                        }))
                      }
                    />
                    <button
                      className="secondary-button"
                      disabled={
                        busy === record.id || !(owners[record.id] ?? "").trim()
                      }
                      onClick={() =>
                        void act(record.id, () =>
                          assignException(record.id, owners[record.id] ?? ""),
                        )
                      }
                    >
                      Assign
                    </button>
                    <button
                      className="secondary-button"
                      disabled={busy === record.id}
                      onClick={() =>
                        void act(record.id, () => closeException(record.id))
                      }
                    >
                      Close
                    </button>
                  </div>
                )}

                <button
                  className="link-button"
                  onClick={() =>
                    setPayloadOpen(payloadOpen === record.id ? null : record.id)
                  }
                >
                  {payloadOpen === record.id ? "Hide payload" : "View payload"}
                </button>
              </footer>

              {payloadOpen === record.id && (
                <pre className="exception-payload">
                  {JSON.stringify(record.payload, null, 2)}
                </pre>
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="panel">
          <EmptyState
            label={
              state === "open"
                ? "Nothing open. Every exception here has been dealt with."
                : `No ${state} exceptions.`
            }
          />
        </div>
      )}
    </div>
  );
}
