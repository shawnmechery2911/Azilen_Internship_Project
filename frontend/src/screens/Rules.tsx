import { useCallback, useEffect, useState } from "react";
import {
  getValidationRules,
  updateValidationRule,
  type ValidationRule,
} from "../api";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";

const GROUPS = ["Completeness", "Format", "Business"] as const;

export function RulesScreen() {
  const [rules, setRules] = useState<ValidationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("All");
  const [savedRule, setSavedRule] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRules(await getValidationRules());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function toggle(
    rule: ValidationRule,
    changes: { enabled?: boolean; required?: boolean },
  ) {
    setBusy(rule.id);
    setError("");
    try {
      await updateValidationRule(rule.id, changes);
      setSavedRule(rule.id);
      setTimeout(() => setSavedRule((current) => (current === rule.id ? null : current)), 1200);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update the rule",
      );
    } finally {
      setBusy(null);
    }
  }
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading validation rules..." />
      </div>
    );
  if (error && !rules.length)
    return (
      <div className="page-wrap">
        <ErrorPanel message={error} retry={() => void load()} />
      </div>
    );
  if (!rules.length)
    return (
      <div className="page-wrap">
        <EmptyState label="No validation rules configured." />
      </div>
    );
  const filteredRules =
    filter === "All"
      ? rules
      : rules.filter((rule) => rule.ats === null || rule.ats === filter);
  return (
    <div className="page-wrap">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Configuration</div>
          <h1>Validation rules</h1>
          <p>
            Enabled — check this rule at all. Required — the field must be present.
            A rule can be enabled but not required, which means: if the value is
            there it must be valid, but it is allowed to be missing.
          </p>
        </div>
      </section>
      {error && <div className="toast">{error}</div>}
      <div className="filter-group" style={{ marginBottom: 16 }}>
        {['All', 'ideal-ats', 'vsys'].map((option) => (
          <button
            key={option}
            className={filter === option ? "filter-active" : ""}
            onClick={() => setFilter(option)}
          >
            {option}
          </button>
        ))}
      </div>
      {GROUPS.map((group) => {
        const inGroup = filteredRules.filter((rule) => rule.group === group);
        if (!inGroup.length) return null;
        return (
          <section className="panel rules-section" key={group}>
            <div className="panel-heading">
              <div>
                <span className="section-kicker">{inGroup.length} rules</span>
                <h2>{group}</h2>
              </div>
            </div>
            <div className="rules-table">
              <div className="rules-header">
                <span>Field</span>
                <span>Check</span>
                <span>Partner</span>
                <span>Must be present</span>
                <span>Rule active</span>
              </div>
              {inGroup.map((rule) => (
                <div
                  className={`rules-row ${rule.enabled ? "" : "rule-off"}`}
                  key={rule.id}
                >
                  <code>{rule.field}</code>
                  <span>
                    {rule.description}
                    {rule.pattern && <small>{rule.pattern}</small>}
                    {rule.allowed_values.length > 0 && (
                      <small>one of: {rule.allowed_values.join(", ")}</small>
                    )}
                  </span>
                  <span>{rule.ats ?? "all"}</span>
                  <div>
                    <input
                      type="checkbox"
                      aria-label={`${rule.field} required`}
                      checked={rule.required}
                      disabled={busy === rule.id}
                      onChange={(event) =>
                        void toggle(rule, { required: event.target.checked })
                      }
                    />
                    {savedRule === rule.id && <small>Saved</small>}
                  </div>
                  <input
                    type="checkbox"
                    aria-label={`${rule.field} enabled`}
                    checked={rule.enabled}
                    disabled={busy === rule.id}
                    onChange={(event) =>
                      void toggle(rule, { enabled: event.target.checked })
                    }
                  />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
