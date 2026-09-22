import { useEffect, useState } from "react";
import { addPartnerSample, getPartners, type Partner } from "../api";
import { ProcessPanel } from "../components/ProcessPanel";

/** Add an order to a partner's stored set.
 *
 *  Onboarding leaves one sample and clean orders add themselves, which runs
 *  the pipeline but does not exercise it: showing what happens when a partner
 *  renames a field needs a payload in the new shape, and waiting for them to
 *  send one is not an option. */
function AddOrder({
  partners,
  onAdded,
}: {
  partners: Partner[];
  onAdded: () => void;
}) {
  const [ats, setAts] = useState("");
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setAts((current) => current || partners[0]?.ats || "");
  }, [partners]);

  async function save(raw: string) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const result = await addPartnerSample(ats, raw);
      setNote(
        result.added
          ? `Kept. ${ats} now has ${result.stored} stored order${result.stored === 1 ? "" : "s"}.`
          : "That is identical to an order already kept, so nothing changed.",
      );
      setText("");
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not keep that order");
    } finally {
      setBusy(false);
    }
  }

  async function pick(file: File | undefined) {
    if (!file) return;
    await save(await file.text());
  }

  return (
    <section className="panel">
      <div className="panel-head-row">
        <h2>Add an order</h2>
        <span className="status-pill">No model call</span>
      </div>
      <p className="empty-note">
        Paste or upload a payload to keep it alongside the ones this partner has
        really sent. Rename a field in it and send it back to watch drift catch
        the change. These are the same stored orders replay checks a new mapping
        against, so an order this partner would never send will hold up later
        approvals.
      </p>

      <div className="process-controls">
        <label className="sr-only" htmlFor="add-partner">
          Partner
        </label>
        <select
          id="add-partner"
          value={ats}
          onChange={(event) => setAts(event.target.value)}
        >
          {partners.map((item) => (
            <option key={item.ats} value={item.ats}>
              {item.ats}
            </option>
          ))}
        </select>
        <input
          type="file"
          accept=".json,.xml,application/json,text/xml"
          disabled={busy || !ats}
          onChange={(event) => void pick(event.target.files?.[0])}
        />
      </div>

      <label className="sr-only" htmlFor="add-payload">
        Payload
      </label>
      <textarea
        id="add-payload"
        className="payload-input"
        placeholder="…or paste JSON or XML here"
        value={text}
        spellCheck={false}
        onChange={(event) => setText(event.target.value)}
      />
      <div className="process-controls">
        <button
          className="primary-button"
          disabled={busy || !ats || !text.trim()}
          onClick={() => void save(text)}
        >
          {busy ? "Keeping..." : "Keep this order"}
        </button>
      </div>
      {error && <div className="toast">{error}</div>}
      {note && <p className="filter-note">{note}</p>}
    </section>
  );
}

export function TestOrderScreen({
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
  const [reload, setReload] = useState(0);

  useEffect(() => {
    void getPartners()
      .then((found) => setPartners(found.filter((item) => item.version !== null)))
      .catch(() => setPartners([]));
  }, [reload]);

  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Operations</div>
          <h1>Test orders</h1>
          <p>
            Send an order through the live pipeline. Nothing here calls a model:
            an approved mapping is applied as it stands, which is the whole
            point of approving it.
          </p>
        </div>
      </section>

      <ProcessPanel key={reload} onReview={onReview} />
      {partners.length > 0 && (
        <AddOrder partners={partners} onAdded={() => setReload((n) => n + 1)} />
      )}
    </div>
  );
}
