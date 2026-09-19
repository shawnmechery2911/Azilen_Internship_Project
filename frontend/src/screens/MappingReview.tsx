import { useEffect, useMemo, useState } from "react";
import {
  type FieldMapping,
  approveMapping,
  editDraftMapping,
  getDestinationFields,
  getPartnerSourceFields,
  getFixtures,
  getReplay,
  getVersions,
  type FixturePayload,
  type SourceField,
  type MappingVersion,
  type ReplayResult,
} from "../api";
import { Link2Off } from "lucide-react";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";
import { EditIcon } from "../components/EditIcon";

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
  onApproved,
}: {
  ats: string;
  payloadType: string;
  version: number;
  onDone: () => void;
  onApproved?: (ats: string) => void;
}) {
  const [mapping, setMapping] = useState<MappingVersion | null>(null);
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [destinations, setDestinations] = useState<string[]>([]);
  const [fixtures, setFixtures] = useState<FixturePayload[]>([]);
  const [previous, setPrevious] = useState<MappingVersion | null>(null);
  const [onlyChanges, setOnlyChanges] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [sourceFields, setSourceFields] = useState<SourceField[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftSource, setDraftSource] = useState("");
  // free text is a deliberate choice, not the only way in
  const [typing, setTyping] = useState(false);
  const [saving, setSaving] = useState(false);
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
      getPartnerSourceFields(ats).then(setSourceFields).catch(() => setSourceFields([]));
      setMapping(versions.find((item) => item.version === version) ?? null);
      // the version immediately before this one is what a reviewer is
      // approving a change against
      const earlier = versions
        .filter((item) => item.version < version)
        .sort((a, b) => b.version - a.version);
      setPrevious(earlier[0] ?? null);
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

  /** What actually changed since the previous version, keyed by destination. */
  const diff = useMemo(() => {
    const before = new Map<string, FieldMapping>();
    for (const rule of previous?.mappings ?? []) before.set(rule.destination, rule);
    const added = new Set<string>();
    const changed = new Map<string, FieldMapping>();
    for (const rule of mapping?.mappings ?? []) {
      const was = before.get(rule.destination);
      if (!was) {
        added.add(rule.destination);
      } else if (
        was.source !== rule.source ||
        was.transform !== rule.transform ||
        was.required !== rule.required ||
        was.source_is_list !== rule.source_is_list
      ) {
        changed.set(rule.destination, was);
      }
      before.delete(rule.destination);
    }
    return { added, changed, removed: [...before.values()] };
  }, [mapping, previous]);

  const changeCount = diff.added.size + diff.changed.size + diff.removed.length;

  function startEdit(destination: string, current: string) {
    setEditing(destination);
    setDraftSource(current);
    // a source the dropdown does not offer - a constant, or a path from a
    // payload we have not kept - opens straight into the text box
    setTyping(
      Boolean(current) && !sourceFields.some((f) => f.path === current),
    );
  }

  async function saveEdit(destination: string, remove = false) {
    setSaving(true);
    setError("");
    try {
      await editDraftMapping(ats, payloadType, version, {
        destination,
        ...(remove ? { remove: true } : { source: draftSource }),
        edited_by: reviewer.trim() || "reviewer",
      });
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save that change");
    } finally {
      setSaving(false);
    }
  }

  async function approve() {
    setBusy(true);
    setError("");
    try {
      await approveMapping(ats, payloadType, version, reviewer);
      if (onApproved) onApproved(ats);
      else onDone();
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
        <Loading label="Loading mapping review..." rows={5} />
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

  /** A draft can be corrected; an approved version is history. */
  const canEdit = mapping.status === "draft";

  const TYPE_IT = "__type__";

  function sourcePicker(destination: string) {
    return (
      <span className="map-edit">
        <label className="sr-only" htmlFor={`src-${destination}`}>
          Source field for {destination}
        </label>
        {typing ? (
          <input
            id={`src-${destination}`}
            autoFocus
            value={draftSource}
            onChange={(event) => setDraftSource(event.target.value)}
            placeholder="Person.Email or Static:value"
          />
        ) : (
          <select
            id={`src-${destination}`}
            value={
              sourceFields.some((f) => f.path === draftSource) ? draftSource : ""
            }
            onChange={(event) => {
              if (event.target.value === TYPE_IT) {
                setTyping(true);
                setDraftSource("");
              } else {
                setDraftSource(event.target.value);
              }
            }}
          >
            <option value="" disabled>
              Choose a field {sourceFields.length ? "" : "(none known yet)"}
            </option>
            {sourceFields.map((field) => (
              <option key={field.path} value={field.path}>
                {field.example
                  ? `${field.path} — ${field.example.slice(0, 32)}`
                  : field.path}
              </option>
            ))}
            <option value={TYPE_IT}>Type it instead...</option>
          </select>
        )}
        <button
          className="secondary-button"
          disabled={saving || !draftSource.trim()}
          onClick={() => void saveEdit(destination)}
        >
          Save
        </button>
        <button
          className="link-button"
          onClick={() => {
            setEditing(null);
            setTyping(false);
          }}
        >
          Cancel
        </button>
      </span>
    );
  }

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
            {mapping.edited_by?.length
              ? ` · edited by ${mapping.edited_by.join(", ")}`
              : ""}
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
        {previous && (
          <div>
            <strong>{changeCount}</strong>
            <span>changed since v{previous.version}</span>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head-row">
          <h2>Field mappings</h2>
          {previous && (
            <div className="filter-group">
              <button
                className={onlyChanges ? "" : "filter-active"}
                onClick={() => setOnlyChanges(false)}
              >
                all {mapping.mappings.length}
              </button>
              <button
                className={onlyChanges ? "filter-active" : ""}
                onClick={() => setOnlyChanges(true)}
              >
                changed since v{previous.version} ({changeCount})
              </button>
            </div>
          )}
        </div>
        <div className="map-table">
          <div className="map-head">
            <span>{ats} sends</span>
            <span />
            <span>we store it as</span>
            <span>example</span>
            <span />
          </div>
          {mapping.mappings
            .filter(
              (rule) =>
                !onlyChanges ||
                diff.added.has(rule.destination) ||
                diff.changed.has(rule.destination),
            )
            .map((rule, index) => {
            const example = sample ? valueAt(sample, rule.source) : null;
            const source = describeSource(rule.source);
            const wasRule = previous ? diff.changed.get(rule.destination) : undefined;
            const isNew = Boolean(previous) && diff.added.has(rule.destination);
            const notes = [
              rule.transform && rule.transform !== "identity"
                ? `transform: ${rule.transform}`
                : null,
              rule.source_is_list ? "list" : null,
              rule.required ? "required" : null,
            ].filter(Boolean);
            return (
              <div
                className={`map-line${isNew ? " map-line-new" : ""}${wasRule ? " map-line-changed" : ""}`}
                key={`${rule.destination}-${index}`}
              >
                <span className="map-src">
                  {editing === rule.destination ? (
                    sourcePicker(rule.destination)
                  ) : (
                    <>
                      <code>{source.text}</code>
                      {source.constant && <em className="map-const">constant</em>}
                      {isNew && <em className="map-tag map-tag-new">new</em>}
                      {wasRule && <em className="map-tag map-tag-changed">changed</em>}
                    </>
                  )}
                </span>
                <span className="map-arrow" aria-hidden="true">
                  →
                </span>
                <code className="map-dest">{rule.destination}</code>
                <span className="map-sample">
                  {source.constant ? "" : (example ?? "—")}
                </span>
                <span className="map-actions">
                  {canEdit && editing !== rule.destination && (
                    <>
                      <button
                        className="icon-action"
                        title="Change which field feeds this"
                        aria-label={`Change the source for ${rule.destination}`}
                        onClick={() => startEdit(rule.destination, rule.source)}
                      >
                        <EditIcon />
                      </button>
                      <button
                        className="icon-action icon-danger"
                        title="Remove this mapping"
                        aria-label={`Unmap ${rule.destination}`}
                        disabled={saving}
                        onClick={() => void saveEdit(rule.destination, true)}
                      >
                        <Link2Off size={14} />
                      </button>
                    </>
                  )}
                </span>
                {wasRule && (
                  <span className="map-note map-was">
                    was <code>{describeSource(wasRule.source).text}</code>
                  </span>
                )}
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
          {diff.removed.map((rule, index) => (
            <div
              className="map-line map-line-removed"
              key={`removed-${rule.destination}-${index}`}
            >
              <span className="map-src">
                <code>{describeSource(rule.source).text}</code>
                <em className="map-tag map-tag-removed">removed</em>
              </span>
              <span className="map-arrow" aria-hidden="true">
                →
              </span>
              <code className="map-dest">{rule.destination}</code>
              <span className="map-sample" />
            </div>
          ))}
        </div>
        {previous && changeCount === 0 && (
          <EmptyState
            label={`Nothing changed between v${previous.version} and v${version}.`}
          />
        )}
      </section>

      <div className="content-grid">
        <div className="panel">
          <h2>Not mapped</h2>
          {mapping.abstentions.length ? (
            mapping.abstentions.map((item, index) => (
              <div className="map-row" key={`${item.destination}-${index}`}>
                <code className="map-dest">{item.destination}</code>
                <span className="map-reason">{item.reason}</span>
                {canEdit &&
                  (editing === item.destination ? (
                    sourcePicker(item.destination)
                  ) : (
                    <button
                      className="link-button"
                      onClick={() => startEdit(item.destination, "")}
                    >
                      Map it yourself
                    </button>
                  ))}
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
