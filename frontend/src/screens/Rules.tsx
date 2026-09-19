import { useCallback, useEffect, useState } from "react";
import {
  bindValidationRule,
  getPartners,
  getValidationRules,
  updateValidationRule,
  type Partner,
  type ValidationRule,
} from "../api";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";

const GROUPS = ["Completeness", "Format", "Business"] as const;

export function RulesScreen() {
  const [rules, setRules] = useState<ValidationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [partners, setPartners] = useState<Partner[]>([]);
  // "" means the catalogue itself - the default every partner starts from
  const [scope, setScope] = useState<string>("");
  const [savedRule, setSavedRule] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextRules, nextPartners] = await Promise.all([
        getValidationRules(scope || undefined),
        getPartners(),
      ]);
      setRules(nextRules);
      setPartners(nextPartners);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load rules");
    } finally {
      setLoading(false);
    }
  }, [scope]);
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
      // a partner scope writes a binding; the catalogue scope writes the rule
      if (scope) {
        await bindValidationRule(scope, rule.id, changes);
      } else {
        await updateValidationRule(rule.id, changes);
      }
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
        <div className="panel">
          <EmptyState label="No validation rules configured." />
        </div>
      </div>
    );
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
        <button
          className={scope === "" ? "filter-active" : ""}
          onClick={() => setScope("")}
        >
          catalogue default
        </button>
        {partners.map((partner) => (
          <button
            key={partner.ats}
            className={scope === partner.ats ? "filter-active" : ""}
            onClick={() => setScope(partner.ats)}
          >
            {partner.ats}
          </button>
        ))}
      </div>
      {GROUPS.map((group) => {
        const inGroup = rules.filter((rule) => rule.group === group);
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
                  <div className="rules-cell">
                    <label className="switch">
                      <input
                        type="checkbox"
                        aria-label={`${rule.field} must be present`}
                        checked={rule.required}
                        disabled={busy === rule.id}
                        onChange={(event) =>
                          void toggle(rule, { required: event.target.checked })
                        }
                      />
                      <span className="track" />
                      <span className="thumb" />
                    </label>
                    {savedRule === rule.id && <small>Saved</small>}
                  </div>
                  <label className="switch">
                    <input
                      type="checkbox"
                      aria-label={`${rule.field} rule active`}
                      checked={rule.enabled}
                      disabled={busy === rule.id}
                      onChange={(event) =>
                        void toggle(rule, { enabled: event.target.checked })
                      }
                    />
                    <span className="track" />
                    <span className="thumb" />
                  </label>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
