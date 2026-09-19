import { useEffect, useState } from "react";
import {
  assignException,
  closeException,
  getExceptions,
  type ExceptionRecord,
} from "../api";
import { ErrorPanel, Loading, EmptyState } from "../components/ScreenState";
import { IssueList } from "../components/IssueList";

export function ExceptionsScreen() {
  const [records, setRecords] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [owners, setOwners] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
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
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading exceptions..." />
      </div>
    );
  if (error && !records.length)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );
  if (!records.length)
    return (
      <div className="page-wrap">
        <EmptyState label="No exceptions available." />
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
      {error && <div className="toast">{error}</div>}
      <section className="panel exception-list">
        {records.map((record) => (
          <article className="mapping-rule" key={record.id}>
            <strong>
              {record.ats} / {record.payload_type} · {record.status}
            </strong>
            <span>
              v{record.mapping_version ?? "-"} ·{" "}
              {new Date(record.created_at).toLocaleString()} ·{" "}
              {record.owner ? `Owner: ${record.owner}` : "Unassigned"}
            </span>
            <IssueList issues={record.issues} />
            <div className="exception-actions">
              <input
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
              {record.status === "open" && (
                <button
                  className="primary-button"
                  disabled={busy === record.id}
                  onClick={() =>
                    void act(record.id, () => closeException(record.id))
                  }
                >
                  Close
                </button>
              )}
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
