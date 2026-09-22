import { useCallback, useEffect, useState } from "react";
import {
  bindValidationRule,
  getMapping,
  getPartners,
  getValidationRules,
  updateValidationRule,
  updateValidationRuleGroup,
  type Partner,
  type ValidationRule,
} from "../api";
import { EmptyState, ErrorPanel, Loading } from "../components/ScreenState";

const GROUPS = ["Completeness", "Format", "Business"] as const;

/** Whether a rule is actually doing anything, which is what its switch shows.
 *  A Completeness rule needs both flags: `enabled` off means the rule has no
 *  opinion and the mapping's own required flag decides, so showing it as on
 *  because `required` is set would promise a check that never runs. */
function isOn(rule: ValidationRule): boolean {
  return rule.group === "Completeness"
    ? rule.required && rule.enabled
    : rule.enabled;
}

export function RulesScreen({ scope: initial }: { scope?: string | null } = {}) {
  const [rules, setRules] = useState<ValidationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [partners, setPartners] = useState<Partner[]>([]);
  // "" means the catalogue itself - the default every partner starts from
  const [scope, setScope] = useState<string>(initial ?? "");
  const justApproved = Boolean(initial) && scope === initial;
  const onFromMapping = rules.filter(
    (rule) => rule.group === "Completeness" && isOn(rule),
  ).length;
  const [savedRule, setSavedRule] = useState<string | null>(null);
  // Destinations this partner's approved mapping fills. Demanding a field the
  // partner never sends turns every one of their orders into an exception, so
  // the ones they do send are worth pointing out.
  const [sends, setSends] = useState<Set<string> | null>(null);
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
      const partner = nextPartners.find((item) => item.ats === scope);
      if (!partner) {
        setSends(null);
      } else {
        // a partner with no approved mapping yet simply has nothing to say here
        const mapping = await getMapping(partner.ats, partner.payload_type).catch(
          () => null,
        );
        setSends(
          mapping ? new Set(mapping.mappings.map((row) => row.destination)) : null,
        );
      }
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
  async function toggleGroup(group: string, on: boolean) {
    setBusy(group);
    setError("");
    try {
      await updateValidationRuleGroup(
        group,
        // Completeness sets both: `required` is the choice, and `enabled` has
        // to be on for that choice to be read at all.
        group === "Completeness" ? { required: on, enabled: true } : { enabled: on },
        scope || undefined,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update the group");
    } finally {
      setBusy(null);
    }
  }
  if (loading)
    return (
      <div className="page-wrap">
        <Loading label="Loading validation rules..." rows={6} />
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
            Completeness rules decide whether a field has to be there. Format
            and Business rules check a value whenever one is present, so they
            cost nothing to leave on.
          </p>
        </div>
      </section>
      {justApproved && (
        <div className="filter-note">
          <span>
            <strong>{initial}</strong> is approved.{" "}
            {onFromMapping > 0 ? (
              <>
                The {onFromMapping} field
                {onFromMapping === 1 ? "" : "s"} its mapping always fills{" "}
                {onFromMapping === 1 ? "is" : "are"} already switched on. Change
                anything that looks wrong.
              </>
            ) : (
              <>Choose what it must send - shape checks already apply.</>
            )}
          </span>
        </div>
      )}
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
        const on = inGroup.filter(isOn).length;
        const allOn = on === inGroup.length;
        return (
          <section className="panel rules-section" key={group}>
            <div className="panel-heading">
              <div>
                <span className="section-kicker">{inGroup.length} rules</span>
                <h2>{group}</h2>
              </div>
              <div className="rules-bulk">
                <span className="rules-count">
                  {on} of {inGroup.length} on
                </span>
                <button
                  className="secondary-button"
                  disabled={busy === group}
                  onClick={() => void toggleGroup(group, !allOn)}
                >
                  {allOn ? "Clear all" : "Select all"}
                </button>
              </div>
            </div>
            <div className="rules-table">
              <div className="rules-header">
                <span>Field</span>
                <span>Check</span>
                <span>
                  {group === "Completeness" ? "Must be present" : "Rule active"}
                </span>
              </div>
              {inGroup.map((rule) => (
                <div
                  className={`rules-row ${isOn(rule) ? "" : "rule-off"}`}
                  key={rule.id}
                >
                  <code>{rule.field}</code>
                  <span>
                    {rule.description}
                    {/* Only worth saying for presence: a Format rule on a field
                        the partner never sends costs nothing, while demanding
                        that field fails every order they place. */}
                    {sends && group === "Completeness" && !sends.has(rule.field) && (
                      <small className="rule-unsent">{scope} does not send this</small>
                    )}
                    {rule.pattern && <small>{rule.pattern}</small>}
                    {rule.allowed_values.length > 0 && (
                      <small>one of: {rule.allowed_values.join(", ")}</small>
                    )}
                  </span>
                  <div className="rules-cell">
                    {/* Presence is the whole of a Completeness rule, so one
                        switch says everything. For a Format or Business rule
                        presence is beside the point - the shape check runs
                        whenever a value is there - so its switch turns the
                        check itself on and off. */}
                    <label className="switch">
                      <input
                        type="checkbox"
                        aria-label={
                          group === "Completeness"
                            ? `${rule.field} must be present`
                            : `${rule.field} rule active`
                        }
                        checked={isOn(rule)}
                        disabled={busy === rule.id || busy === group}
                        onChange={(event) =>
                          void toggle(
                            rule,
                            group === "Completeness"
                              ? { required: event.target.checked, enabled: true }
                              : { enabled: event.target.checked },
                          )
                        }
                      />
                      <span className="track" />
                      <span className="thumb" />
                    </label>
                    {savedRule === rule.id && <small>Saved</small>}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
