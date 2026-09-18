import { AlertTriangle, ArrowRight, Check } from "lucide-react";
import type { ProcessResult, Sample } from "../api";

export function PayloadView({
  sample,
  result,
}: {
  sample: Sample;
  result: ProcessResult;
}) {
  const ok = result.status === "processed";
  return (
    <section className="payload-view">
      <div className="panel-heading activity-heading">
        <div>
          <span className="section-kicker">
            {sample.ats} · mapping v{result.mapping_version ?? "-"} · 0 AI calls
          </span>
          <h2>{sample.label}</h2>
        </div>
        <span className={`result-pill ${ok ? "result-good" : "result-bad"}`}>
          <span />
          {ok ? "processed" : "exception"}
        </span>
      </div>
      <div className="payload-grid">
        <div className="payload-col">
          <div className="payload-label">
            Source payload<span>as the partner sent it</span>
          </div>
          <pre>{JSON.stringify(sample.data, null, 2)}</pre>
        </div>
        <div className="payload-arrow">
          <ArrowRight size={18} />
        </div>
        <div className="payload-col">
          <div className="payload-label">
            Mapped output<span>our canonical shape</span>
          </div>
          <pre>{JSON.stringify(result.mapped_payload, null, 2)}</pre>
        </div>
      </div>
      {result.issues.length > 0 ? (
        <div className="payload-issues">
          <div className="payload-issues-head">
            <AlertTriangle size={16} />
            <strong>
              {result.issues.length} field
              {result.issues.length === 1 ? "" : "s"} failed
            </strong>
          </div>
          <ul>
            {result.issues.map((issue) => (
              <li key={issue.field}>
                <code>{issue.field}</code>
                <span>{issue.message}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="payload-clean">
          <Check size={16} />
          Every mapped field resolved. No AI was involved in this transform.
        </div>
      )}
    </section>
  );
}
