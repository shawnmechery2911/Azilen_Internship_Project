import { useEffect, useState } from "react";
import { ErrorPanel } from "../components/ScreenState";
import { draftMapping, getDestinationFields, parsePayload } from "../api";

export function OnboardingScreen({
  onReview,
}: {
  onReview: (ats: string, payloadType: string, version: number) => void;
}) {
  const [file, setFile] = useState<Record<string, unknown> | null>(null);
  const [ats, setAts] = useState("");
  const [payloadType, setPayloadType] = useState("candidate");
  const [fields, setFields] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  useEffect(() => {
    void getDestinationFields()
      .then((items) => setFields(items.join("\n")))
      .catch(() =>
        setFields(
          "Applicant.Email\nApplicant.Names[0].GivenName\nApplicant.SSN",
        ),
      );
  }, []);
  async function onFile(selected: File) {
    setError("");
    setFileName(selected.name);
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
      const result = await draftMapping(
        ats,
        payloadType,
        file,
        fields
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
      );
      onReview(ats, payloadType, result.version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Draft failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Partner onboarding</div>
          <h1>Draft a mapping</h1>
          <p>
            AI is used only here to propose a mapping. You approve what reaches
            runtime.
          </p>
        </div>
      </section>
      {error && <ErrorPanel message={error} retry={() => void draft()} />}
      <div className="panel onboarding-form">
        <label>
          Partner code
          <input
            value={ats}
            onChange={(event) => setAts(event.target.value)}
            placeholder="new-partner"
          />
        </label>
        <label>
          Payload type
          <input
            value={payloadType}
            onChange={(event) => setPayloadType(event.target.value)}
          />
        </label>
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
          {fileName && <small>Parsed: {fileName}</small>}
        </label>
        {file && <pre>{JSON.stringify(file, null, 2)}</pre>}
        <label>
          Destination fields
          <textarea
            value={fields}
            onChange={(event) => setFields(event.target.value)}
          />
        </label>
        <button
          className="primary-button"
          disabled={!file || !ats.trim() || busy}
          onClick={() => void draft()}
        >
          {busy
            ? "AI is drafting, this may take a few seconds..."
            : "Draft mapping"}
        </button>
      </div>
    </div>
  );
}
