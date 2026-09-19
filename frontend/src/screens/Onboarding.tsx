import { useEffect, useMemo, useState } from "react";
import { ErrorPanel } from "../components/ScreenState";
import { draftMapping, getDestinationFields, parsePayload } from "../api";

/** Every leaf path in the uploaded sample - what the model has to work with. */
function leafPaths(node: unknown, prefix = ""): string[] {
  if (node === null || node === undefined) return prefix ? [prefix] : [];
  if (Array.isArray(node)) return leafPaths(node[0], prefix);
  if (typeof node === "object") {
    return Object.entries(node as Record<string, unknown>).flatMap(
      ([key, value]) => leafPaths(value, prefix ? `${prefix}.${key}` : key),
    );
  }
  return prefix ? [prefix] : [];
}

export function OnboardingScreen({
  onReview,
}: {
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [file, setFile] = useState<Record<string, unknown> | null>(null);
  const [ats, setAts] = useState("");
  const [payloadType, setPayloadType] = useState("candidate");
  const [destinations, setDestinations] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    void getDestinationFields()
      .then(setDestinations)
      .catch(() => setDestinations([]));
  }, []);

  const sourcePaths = useMemo(() => (file ? leafPaths(file) : []), [file]);

  async function onFile(selected: File) {
    setError("");
    setFileName(selected.name);
    setShowRaw(false);
    try {
      const parsed = await parsePayload(await selected.text());
      setFile(parsed.payload);
    } catch (err) {
      setFile(null);
      setError(err instanceof Error ? err.message : "Could not read that file");
    }
  }

  async function draft() {
    if (!file || !ats.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await draftMapping(ats, payloadType, file, destinations);
      onReview(ats, payloadType, result.version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft failed");
    } finally {
      setBusy(false);
    }
  }

  const blockedReason = !ats.trim()
    ? "Enter a partner code"
    : !payloadType.trim()
      ? "Enter a payload type"
      : !file
        ? "Upload a sample order first"
        : "";

  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Partner onboarding</div>
          <h1>Draft a mapping</h1>
        </div>
      </section>

      {error && <ErrorPanel message={error} retry={() => void draft()} />}

      <section className="panel step">
        <div className="step-mark">1</div>
        <div className="step-body">
          <h2>Identify the partner</h2>
          <div className="onboarding-form step-fields">
            <label>
              Partner code
              <input
                value={ats}
                onChange={(event) => setAts(event.target.value)}
                placeholder="acme-ats"
              />
            </label>
            <label>
              Payload type
              <input
                value={payloadType}
                onChange={(event) => setPayloadType(event.target.value)}
                placeholder="candidate"
              />
            </label>
          </div>
        </div>
      </section>

      <section className="panel step">
        <div className="step-mark">2</div>
        <div className="step-body">
          <h2>Upload one of their orders</h2>
          <div className="onboarding-form">
            <label>
              Sample JSON or XML
              <input
                type="file"
                accept=".json,.xml"
                onChange={(event) => {
                  const selected = event.target.files?.[0];
                  if (selected) void onFile(selected);
                }}
              />
            </label>
          </div>

          {file && (
            <div className="parse-result">
              <span className="parse-summary">
                <strong>{fileName}</strong> parsed ·{" "}
                {sourcePaths.length} source field
                {sourcePaths.length === 1 ? "" : "s"} found ·{" "}
                {destinations.length} to map onto
              </span>
              <button
                className="link-button"
                onClick={() => setShowRaw(!showRaw)}
              >
                {showRaw ? "Hide parsed payload" : "View parsed payload"}
              </button>
              {showRaw && (
                <pre>{JSON.stringify(file, null, 2)}</pre>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="panel step">
        <div className="step-mark">3</div>
        <div className="step-body">
          <h2>Let the model propose a mapping</h2>
          <div className="step-action">
            {blockedReason && (
              <span className="approve-reason">{blockedReason}</span>
            )}
            <button
              className="primary-button"
              disabled={Boolean(blockedReason) || busy}
              onClick={() => void draft()}
            >
              {busy ? "Drafting..." : "Draft mapping"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
