"""HTTP layer for the ATS mapping pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict, replace

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bedrock_proposer import make_adapter
from pipeline import AiUsageLog, get_path, DriftTracker, ExceptionQueue, MappingStore, Pipeline, PayloadShape, RuleBindingStore, SamplePayloadStore, ValidationRuleStore, apply_mapping, parse_input

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Mapping Pipeline")
store = MappingStore(ROOT / "mapping_store.json")
queue = ExceptionQueue(ROOT / "exceptions.json")
tracker = DriftTracker(path=ROOT / "drift_counts.json")
shapes = PayloadShape(ROOT / "payload_shapes.json")
rules_store = ValidationRuleStore(ROOT / "validation_rules.json")
bindings = RuleBindingStore(ROOT / "rule_bindings.json")
samples = SamplePayloadStore(ROOT / "sample_payloads.json")


def rules_for(ats: str):
    """The catalogue as this partner is held to it."""
    return bindings.rules_for(ats, rules_store.all())
from pipeline import ProcessingLog

log = ProcessingLog(ROOT / "processing_log.json")
ai_log = AiUsageLog(ROOT / "ai_usage.json")
FIXTURES = ROOT / "fixtures"


class ApproveRequest(BaseModel):
    reviewer: str


class DraftRequest(BaseModel):
    payload: dict | str
    destination_fields: list[str]


class AssignRequest(BaseModel):
    owner: str


class ParseRequest(BaseModel):
    text: str


class RemapRequest(BaseModel):
    from_source: str
    to_source: str
    proposed_by: str = "drift"


class MappingEdit(BaseModel):
    destination: str
    source: str | None = None
    required: bool | None = None
    transform: str | None = None
    remove: bool = False
    edited_by: str = ""


def leaf_paths(node, prefix: str = "") -> list[str]:
    """Every path a value can be read from in a stored payload."""
    if isinstance(node, list):
        return leaf_paths(node[0], prefix) if node else ([prefix] if prefix else [])
    if isinstance(node, dict):
        found: list[str] = []
        for key, value in node.items():
            found.extend(leaf_paths(value, f"{prefix}.{key}" if prefix else key))
        return found
    return [prefix] if prefix else []


@app.post("/api/parse")
def parse_payload(body: ParseRequest):
    try:
        return {"payload": parse_input(body.text)}
    except Exception as error:
        raise HTTPException(400, f"Could not parse this file: {error}") from error


@app.get("/api/destination-fields")
def get_destination_fields():
    return json.loads((FIXTURES / "destination-fields.json").read_text(encoding="utf-8"))


SEEDED_SAMPLES = {
    "ideal-ats": ["ideallogic-order.json"],
    "vsys": ["vsys-order.xml", "vsys-order-2addresses.xml"],
}


def replay_payloads_for(ats: str) -> list[dict]:
    """What this partner has actually sent.

    This was a hardcoded dictionary of two seeded partner names, so any
    partner onboarded through the UI replayed against nothing and every
    approval sailed through unguarded. Real payloads come first; the seeded
    files remain so the shipped demo partners still have a corpus before
    they have processed anything.
    """
    stored = samples.for_ats(ats)
    if stored:
        return stored
    return [
        parse_input((FIXTURES / name).read_text(encoding="utf-8"))
        for name in SEEDED_SAMPLES.get(ats, [])
    ]


def replay_label(ats: str, index: int) -> str:
    """Name a replayed payload.

    The seeded partners replay against files, so their names are the most
    useful label. Anything a partner actually sent is just their nth stored
    order - this used to index the seeded filename list for every partner,
    which raised IndexError the moment a real partner was replayed.
    """
    names = SEEDED_SAMPLES.get(ats, [])
    if not samples.for_ats(ats) and index < len(names):
        return names[index]
    return f"stored order {index + 1}"


@app.get("/api/partners/{ats}/samples")
def partner_samples(ats: str):
    """Orders this partner has actually sent, to send again as a test.

    The test panel used to offer fixture files tied to two seeded partner
    names, so for any partner onboarded through the UI it sent an order to
    an ats that did not exist.
    """
    payloads = replay_payloads_for(ats)
    return [
        {"label": replay_label(ats, index), "data": payload}
        for index, payload in enumerate(payloads)
    ]


@app.get("/api/partners/{ats}/source-fields")
def partner_source_fields(ats: str):
    """The paths this partner's own payloads actually contain.

    A reviewer correcting a mapping should be choosing from what the partner
    sends, not typing a path from memory.
    """
    seen: list[str] = []
    examples: dict[str, str] = {}
    for payload in replay_payloads_for(ats):
        for path in leaf_paths(payload):
            if path not in seen:
                seen.append(path)
            if path not in examples:
                # the value decides it when the name does not: PartnerSystem
                # and Username are both plausible senders until you see
                # "ideallogic" next to "smcdonald"
                value = get_path(payload, path)
                if isinstance(value, list):
                    value = value[0] if value else None
                if value is not None and not isinstance(value, (dict, list)):
                    examples[path] = str(value)
    # Paths already used by this partner's mappings, so the list is useful even
    # for a draft made before payloads were being kept - at minimum a reviewer
    # sees every source the partner is already mapped from.
    for partner in store.list_partners():
        if partner["ats"] != ats:
            continue
        for version in store.versions_for(ats, partner["payload_type"]):
            for row in version.mappings:
                if not row.source.startswith("Static:") and row.source not in seen:
                    seen.append(row.source)
    return [{"path": path, "example": examples.get(path)} for path in sorted(seen)]


@app.post("/api/mappings/{ats}/{payload_type}/remap")
def remap_source(ats: str, payload_type: str, body: RemapRequest):
    """Point every rule reading one source at another, as a new draft.

    Drift told us the partner renamed a field. Acting on that is a mechanical
    substitution, not a question for the model - and it is a new version
    rather than an edit, because the approved one is what production is
    running and what earlier orders were mapped with.
    """
    current = store.get(ats, payload_type)
    if current is None:
        raise HTTPException(404, "No approved mapping to remap")
    rows = [
        replace(row, source=body.to_source) if row.source == body.from_source else row
        for row in current.mappings
    ]
    if rows == current.mappings:
        raise HTTPException(400, f"No rule reads {body.from_source}")
    version = store.add_draft(ats, payload_type, rows, proposed_by=body.proposed_by)
    # Stored orders still carry the old path. Left in place they fail replay
    # against the very mapping that fixes them, so the guardrail would block
    # the repair and the only way on would be to override it.
    retired = samples.retire(ats, body.from_source, body.to_source)
    return {"version": version.version, "retired_samples": retired}


@app.patch("/api/mappings/{ats}/{payload_type}/{version}/mapping")
def edit_draft_mapping(ats: str, payload_type: str, version: int, body: MappingEdit):
    """Correct one row of a draft before it is approved."""
    try:
        draft = store.edit_draft(
            ats,
            payload_type,
            version,
            body.destination,
            source=body.source,
            required=body.required,
            transform=body.transform,
            remove=body.remove,
            edited_by=body.edited_by,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return asdict(draft)


@app.get("/api/partners")
def get_partners():
    return store.list_partners()


@app.get("/api/fixtures")
def get_fixtures():
    return [
        {"name": "IdealLogic order", "ats": "ideal-ats", "payload_type": "candidate", "data": parse_input((FIXTURES / "ideallogic-order.json").read_text(encoding="utf-8"))},
        {"name": "VSYS order", "ats": "vsys", "payload_type": "background", "data": parse_input((FIXTURES / "vsys-order.xml").read_text(encoding="utf-8"))},
        {"name": "Incomplete order", "ats": "ideal-ats", "payload_type": "candidate", "data": {"Username": "broken"}},
    ]


@app.get("/api/mappings/{ats}/{payload_type}")
def get_mapping(ats: str, payload_type: str):
    mapping = store.get(ats, payload_type)
    if mapping is None:
        raise HTTPException(404, "No approved mapping")
    return mapping


@app.get("/api/mappings/{ats}/{payload_type}/versions")
def get_versions(ats: str, payload_type: str):
    return store.versions_for(ats, payload_type)


@app.post("/api/mappings/{ats}/{payload_type}/{version}/approve")
def approve_mapping(ats: str, payload_type: str, version: int, body: ApproveRequest):
    try:
        approved = store.approve(
            ats,
            payload_type,
            version,
            body.reviewer,
            replay_payloads_for(ats),
            rules_for(ats),
        )
    except ValueError as error:
        raise HTTPException(400, str(error))
    answer_presence_from(ats, approved)
    return approved


def answer_presence_from(ats: str, mapping) -> None:
    """Switch on the presence rules the approved mapping has already answered.

    The mapping says which fields this partner sends, and which of those are
    always there rather than sometimes. That is the same question the
    validation screen asks, so asking it twice means someone either retypes
    the mapping as switches or skips the step and demands nothing.

    A row's own required flag decides, not the mere fact that it is mapped: a
    partner can send a field that is often empty - a middle name, a date of
    birth nobody filled in - and demanding those would turn ordinary orders
    into exceptions.

    Only rules nobody has configured are touched, so approving a second
    version never overwrites a choice someone made by hand.
    """
    already = bindings.for_ats(ats)
    mapped = {row.destination: row.required for row in mapping.mappings}
    by_required: dict[bool, list[str]] = {True: [], False: []}
    for rule in rules_store.all():
        if rule.group != "Completeness" or rule.id in already:
            continue
        if rule.field in mapped:
            by_required[mapped[rule.field]].append(rule.id)
    for required, ids in by_required.items():
        if ids:
            bindings.set_group(ats, ids, enabled=True, required=required)


@app.get("/api/mappings/{ats}/{payload_type}/{version}/replay")
def replay_check(ats: str, payload_type: str, version: int):
    mapping = store.get(ats, payload_type, version)
    if mapping is None:
        raise HTTPException(404, "Version not found")
    results = []
    for index, payload in enumerate(replay_payloads_for(ats)):
        outcome = apply_mapping(mapping, payload, rules_for(ats))
        results.append({
            "payload": replay_label(ats, index),
            "status": outcome.status,
            "issues": [issue["field"] for issue in outcome.issues],
        })
    return {"safe": all(result["status"] == "processed" for result in results), "checked": len(results), "results": results}


@app.post("/api/mappings/{ats}/{payload_type}/draft")
def draft_mapping(ats: str, payload_type: str, body: DraftRequest):
    adapter = make_adapter()
    payload = parse_input(body.payload)
    # the sample that produced this draft is the first thing we know this
    # partner sends, so it becomes the seed of their replay corpus
    samples.remember(ats, payload)
    mappings = adapter.draft(payload, body.destination_fields)
    proposer = getattr(adapter, "proposer", None)
    ai_log.add(ats, payload_type, getattr(proposer, "model_id", "offline-matcher"), getattr(proposer, "last_usage", None))
    version = store.add_draft(
        ats,
        payload_type,
        mappings,
        proposed_by="bedrock",
        abstentions=getattr(adapter, "abstentions", []),
    )
    return {"version": version.version, "mappings": mappings, "abstentions": getattr(adapter, "abstentions", [])}


@app.post("/api/process")
def process_payload(payload: dict):
    pipeline = Pipeline(store, tracker, shapes)
    ats = payload.get("ats", "")
    payload_type = payload.get("payload_type", "")
    data = payload.get("data", {})
    result = pipeline.process(ats, payload_type, data, rules_for(ats))
    log.add(ats, payload_type, result)
    if result.status == "exception":
        queue.add(ats, payload_type, data, result)
    else:
        # an order that mapped cleanly is exactly what a future mapping has to
        # keep handling, so it joins the replay corpus; a failed one proves
        # nothing and would block every later approval
        samples.remember(ats, parse_input(data))
    return result


@app.get("/api/activity")
def get_activity():
    return log.recent()


@app.get("/api/exceptions")
def get_exceptions():
    return queue.all()


@app.post("/api/exceptions/{record_id}/assign")
def assign_exception(record_id: str, body: AssignRequest):
    try:
        return queue.assign(record_id, body.owner)
    except KeyError as error:
        raise HTTPException(404, str(error))


@app.post("/api/exceptions/{record_id}/close")
def close_exception(record_id: str):
    try:
        return queue.close(record_id)
    except KeyError as error:
        raise HTTPException(404, str(error))


@app.get("/api/ai-usage")
def get_ai_usage():
    calls = ai_log.all()
    return {
        "calls": len(calls),
        "input_tokens": sum(item.input_tokens for item in calls),
        "output_tokens": sum(item.output_tokens for item in calls),
        "partners_onboarded": len({item.ats for item in calls}),
        "orders_processed": len(log.recent(100000)),
        "recent": [asdict(item) for item in ai_log.recent(5)],
    }


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    required: bool | None = None


@app.get("/api/validation-rules")
def get_validation_rules(ats: str | None = None):
    rules = rules_for(ats) if ats else rules_store.all()
    return [asdict(rule) for rule in rules]


class RuleGroupUpdate(RuleUpdate):
    group: str


class RuleBindingUpdate(RuleUpdate):
    """What one partner may change about one rule.

    allowed_values narrows, and only narrows. pattern and check stay in the
    catalogue: a partner sending a different date format is a transform on the
    mapping row, not a looser rule, and per-partner shapes would put several
    shapes into a model whose whole job is to have one.
    """

    allowed_values: list[str] | None = None


def narrowing(rule, chosen: list[str]) -> list[str]:
    """Check a proposed narrowing, and refuse anything that is not one."""
    if not rule.allowed_values:
        raise HTTPException(400, f"{rule.id} does not check a value against a list")
    if not chosen:
        raise HTTPException(400, "A rule that allows no value would fail every order")
    stray = [value for value in chosen if value not in rule.allowed_values]
    if stray:
        raise HTTPException(
            400,
            f"{rule.id} does not allow " + ", ".join(stray)
            + ". A partner can be held to fewer values than the model accepts, never more.",
        )
    # covering the whole catalogue list is the same as having no opinion
    return [] if set(chosen) >= set(rule.allowed_values) else chosen


@app.patch("/api/validation-rules")
def update_validation_rule_group(body: RuleGroupUpdate):
    """Set one flag across a whole group of catalogue rules."""
    changes = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None and key != "group"
    }
    if not changes:
        raise HTTPException(400, "Nothing to change")
    touched = rules_store.update_group(body.group, **changes)
    if not touched:
        raise HTTPException(404, f"No rules in group: {body.group}")
    return [asdict(rule) for rule in touched]


@app.patch("/api/partners/{ats}/validation-rules")
def bind_validation_rule_group(ats: str, body: RuleGroupUpdate):
    """Hold one partner to a whole group of rules, or to none of them."""
    changes = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None and key != "group"
    }
    if not changes:
        raise HTTPException(400, "Nothing to change")
    ids = [rule.id for rule in rules_store.all() if rule.group == body.group]
    if not ids:
        raise HTTPException(404, f"No rules in group: {body.group}")
    bindings.set_group(ats, ids, **changes)
    return [asdict(rule) for rule in rules_for(ats) if rule.group == body.group]


@app.patch("/api/validation-rules/{rule_id}")
def update_validation_rule(rule_id: str, body: RuleUpdate):
    """Edit the catalogue rule itself - this is every partner's default."""
    changes = {key: value for key, value in body.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(400, "Nothing to change")
    try:
        return asdict(rules_store.update(rule_id, **changes))
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@app.patch("/api/partners/{ats}/validation-rules/{rule_id}")
def bind_validation_rule(ats: str, rule_id: str, body: RuleBindingUpdate):
    """Decide how one partner is held to one catalogue rule.

    This is the per-onboarding choice, and it touches nothing else: the same
    rule stays exactly as it was for every other partner.
    """
    changes = {key: value for key, value in body.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(400, "Nothing to change")
    rule = next((item for item in rules_store.all() if item.id == rule_id), None)
    if rule is None:
        raise HTTPException(404, f"Unknown rule: {rule_id}")
    if "allowed_values" in changes:
        changes["allowed_values"] = narrowing(rule, changes["allowed_values"])
    bindings.set(ats, rule_id, **changes)
    return next(
        asdict(rule) for rule in rules_for(ats) if rule.id == rule_id
    )


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True))
