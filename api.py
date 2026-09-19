"""HTTP layer for the ATS mapping pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bedrock_proposer import make_adapter
from pipeline import AiUsageLog, DriftTracker, ExceptionQueue, MappingStore, Pipeline, RuleBindingStore, SamplePayloadStore, ValidationRuleStore, apply_mapping, parse_input

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Mapping Pipeline")
store = MappingStore(ROOT / "mapping_store.json")
queue = ExceptionQueue(ROOT / "exceptions.json")
tracker = DriftTracker(path=ROOT / "drift_counts.json")
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
        return store.approve(
            ats,
            payload_type,
            version,
            body.reviewer,
            replay_payloads_for(ats),
            rules_for(ats),
        )
    except ValueError as error:
        raise HTTPException(400, str(error))


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
    pipeline = Pipeline(store, tracker)
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
    calls = ai_log.records
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
def bind_validation_rule(ats: str, rule_id: str, body: RuleUpdate):
    """Decide whether one partner is held to one catalogue rule.

    This is the per-onboarding choice, and it touches nothing else: the same
    rule stays exactly as it was for every other partner.
    """
    changes = {key: value for key, value in body.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(400, "Nothing to change")
    if not any(rule.id == rule_id for rule in rules_store.all()):
        raise HTTPException(404, f"Unknown rule: {rule_id}")
    bindings.set(ats, rule_id, **changes)
    return next(
        asdict(rule) for rule in rules_for(ats) if rule.id == rule_id
    )


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True))
