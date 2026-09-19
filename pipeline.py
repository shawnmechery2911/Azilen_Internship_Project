"""Deterministic ATS payload mapping pipeline.

Mappings are proposed separately from runtime processing. Only approved mapping
versions may be used to transform production payloads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field, replace as replace_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


class JsonBacked:
    path: Path
    _stamp: tuple[int, int] | None

    def _reload_if_changed(self) -> None:
        if file_stamp(self.path) != self._stamp:
            self._load()

    def _load(self) -> None:
        raise NotImplementedError


PATH_PART = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")


def parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for match in PATH_PART.finditer(path):
        parts.append(int(match.group(2)) if match.group(2) is not None else match.group(1))
    if not parts or "".join(str(part) for part in parts) == "":
        raise ValueError(f"Invalid path: {path}")
    return parts


def get_path(payload: Any, path: str, many: bool = False) -> Any:
    """Read dictionaries, indexed arrays, and repeated-list paths."""
    values: list[Any] = [payload]
    for part in parse_path(path):
        next_values: list[Any] = []
        for value in values:
            if isinstance(part, int):
                if isinstance(value, list) and part < len(value):
                    next_values.append(value[part])
            elif isinstance(value, dict) and part in value:
                next_values.append(value[part])
            elif isinstance(value, list):
                next_values.extend(item[part] for item in value if isinstance(item, dict) and part in item)
        values = next_values
        if not values:
            return [] if many else None
    if many:
        return values
    return values[0] if len(values) == 1 else values


def put_path(payload: dict[str, Any], path: str, value: Any) -> None:
    """Write paths such as ``Applicant.Names[0].GivenName``."""
    parts = parse_path(path)
    target: Any = payload
    for index, part in enumerate(parts[:-1]):
        following = parts[index + 1]
        if isinstance(part, int):
            if not isinstance(target, list):
                raise TypeError(f"Cannot index non-list while writing {path}")
            while len(target) <= part:
                target.append({} if not isinstance(following, int) else [])
            target = target[part]
            continue
        if not isinstance(target, dict):
            raise TypeError(f"Cannot write through non-object while writing {path}")
        child = target.get(part)
        if not isinstance(child, (dict, list)):
            child = [] if isinstance(following, int) else {}
            target[part] = child
        target = child
    final = parts[-1]
    if isinstance(final, int):
        if not isinstance(target, list):
            raise TypeError(f"Cannot index non-list while writing {path}")
        while len(target) <= final:
            target.append(None)
        target[final] = value
    else:
        if not isinstance(target, dict):
            raise TypeError(f"Cannot write field while writing {path}")
        target[final] = value


def parse_input(payload: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Normalize JSON or XML at the pipeline boundary."""
    if isinstance(payload, dict):
        return payload
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("JSON payload must be an object")
        return value
    except json.JSONDecodeError:
        return xml_to_dict(text)


def xml_to_dict(xml: str) -> dict[str, Any]:
    def convert(element: ET.Element) -> Any:
        children = list(element)
        if not children:
            return (element.text or "").strip()
        result: dict[str, Any] = {}
        for child in children:
            value = convert(child)
            if child.tag in result:
                if not isinstance(result[child.tag], list):
                    result[child.tag] = [result[child.tag]]
                result[child.tag].append(value)
            else:
                result[child.tag] = value
        return result

    root = ET.fromstring(xml)
    value = convert(root)
    return value if isinstance(value, dict) else {root.tag: value}


@dataclass(frozen=True)
class FieldMapping:
    source: str
    destination: str
    required: bool = False
    transform: str | None = None
    equivalents: dict[str, str] = field(default_factory=dict)
    source_is_list: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class ValidationRule:
    id: str
    field: str
    group: str = "Format"
    description: str = ""
    required: bool = False
    pattern: str | None = None
    allowed_values: tuple[str, ...] = ()
    check: str | None = None
    enabled: bool = True
    ats: str | None = None


def check_min_age_18(value: str) -> str | None:
    try:
        born = datetime.fromisoformat(value).date()
    except ValueError:
        return "Not a date this check can read"
    today = datetime.now(timezone.utc).date()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return None if age >= 18 else f"Applicant is {age}, under the minimum age of 18"


def check_ssn_not_placeholder(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 9:
        return None
    if len(set(digits)) == 1:
        return "Every digit is the same, this is placeholder data"
    if digits.startswith(("000", "666", "9")):
        return "This area number is never issued"
    if digits[3:5] == "00" or digits[5:] == "0000":
        return "Group or serial number is all zeroes"
    return None


BUSINESS_CHECKS = {
    "min_age_18": check_min_age_18,
    "ssn_not_placeholder": check_ssn_not_placeholder,
}


class MappingDraftProvider(Protocol):
    def draft(self, payload: dict[str, Any], destination_fields: Iterable[str]) -> list[FieldMapping]:
        ...


@dataclass
class MappingVersion:
    ats: str
    payload_type: str
    version: int
    mappings: list[FieldMapping]
    abstentions: list[dict[str, str]] = field(default_factory=list)
    status: str = "draft"
    proposed_by: str = "system"
    approved_by: str | None = None
    approved_at: str | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass
class ProcessingResult:
    status: str
    mapped_payload: dict[str, Any]
    issues: list[dict[str, str]]
    mapping_version: int | None
    drift_alerts: list[dict[str, str]] = field(default_factory=list)
    processed_at: str = field(default_factory=utc_now)


@dataclass
class ProcessingRecord:
    id: str
    ats: str
    payload_type: str
    status: str
    mapping_version: int | None
    issue_count: int
    processed_at: str = field(default_factory=utc_now)


@dataclass
class AiCall:
    id: str
    ats: str
    payload_type: str
    model: str
    input_tokens: int
    output_tokens: int
    called_at: str = field(default_factory=utc_now)


class ProcessingLog(JsonBacked):
    """Append-only record of every processed payload."""

    def __init__(self, path: str | Path = "processing_log.json") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.records: list[ProcessingRecord] = []
        self._stamp: int | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            self.records = []
            return
        self.records = [ProcessingRecord(**item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def add(self, ats: str, payload_type: str, result: ProcessingResult) -> ProcessingRecord:
        self._reload_if_changed()
        record = ProcessingRecord(str(uuid.uuid4()), ats, payload_type, result.status, result.mapping_version, len(result.issues))
        self.records.append(record)
        self._save()
        return record

    def recent(self, limit: int = 20) -> list[ProcessingRecord]:
        self._reload_if_changed()
        return sorted(self.records, key=lambda record: record.processed_at, reverse=True)[:limit]

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(item) for item in self.records], indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)


class AiUsageLog(JsonBacked):
    def __init__(self, path: str | Path = "ai_usage.json") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.records: list[AiCall] = []
        self._stamp: int | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            self.records = []
            return
        self.records = [AiCall(**item) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def add(self, ats: str, payload_type: str, model: str, usage: dict[str, Any] | None) -> AiCall:
        self._reload_if_changed()
        usage = usage or {}
        record = AiCall(str(uuid.uuid4()), ats, payload_type, model, int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0)))
        self.records.append(record)
        self._save()
        return record

    def recent(self, limit: int = 10) -> list[AiCall]:
        self._reload_if_changed()
        return sorted(self.records, key=lambda item: item.called_at, reverse=True)[:limit]

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(item) for item in self.records], indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)


@dataclass
class ExceptionRecord:
    id: str
    ats: str
    payload_type: str
    payload: dict[str, Any]
    issues: list[dict[str, str]]
    mapping_version: int | None
    status: str = "open"
    owner: str | None = None
    created_at: str = field(default_factory=utc_now)
    closed_at: str | None = None


class ExceptionQueue(JsonBacked):
    """Persisted queue for field-level mapping and validation failures."""

    def __init__(self, path: str | Path = "exceptions.json") -> None:
        self.path = Path(path)
        self.records: list[ExceptionRecord] = []
        self._lock = threading.Lock()
        self._stamp: int | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            self.records = []
            return
        self.records = [ExceptionRecord(id=item.get("id", str(uuid.uuid4())), **{key: value for key, value in item.items() if key != "id"}) for item in json.loads(self.path.read_text(encoding="utf-8"))]

    def add(self, ats: str, payload_type: str, payload: dict[str, Any], result: ProcessingResult) -> ExceptionRecord:
        self._reload_if_changed()
        record = ExceptionRecord(str(uuid.uuid4()), ats, payload_type, payload, result.issues, result.mapping_version)
        self.records.append(record)
        self._save()
        return record

    def assign(self, record_id: str, owner: str) -> ExceptionRecord:
        self._reload_if_changed()
        record = self._find(record_id)
        record.owner = owner
        self._save()
        return record

    def close(self, record_id: str) -> ExceptionRecord:
        self._reload_if_changed()
        record = self._find(record_id)
        record.status = "closed"
        record.closed_at = utc_now()
        self._save()
        return record

    def _find(self, record_id: str) -> ExceptionRecord:
        for record in self.records:
            if record.id == record_id:
                return record
        raise KeyError(f"Unknown exception record: {record_id}")

    def all(self) -> list[ExceptionRecord]:
        self._reload_if_changed()
        return self.records

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(item) for item in self.records], indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)


class ValidationRuleStore(JsonBacked):
    """JSON-backed validation rules editable without a deploy."""

    def __init__(self, path: str | Path = "validation_rules.json") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.rules: list[ValidationRule] = []
        self._stamp: tuple[int, int] | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            self.rules = []
            return
        self.rules = [
            ValidationRule(**{**item, "allowed_values": tuple(item.get("allowed_values", ()))})
            for item in json.loads(self.path.read_text(encoding="utf-8"))
        ]

    def all(self) -> list[ValidationRule]:
        self._reload_if_changed()
        return self.rules

    def rules_for(self, ats: str) -> list[ValidationRule]:
        self._reload_if_changed()
        overrides = {rule.id: rule for rule in self.rules if rule.ats == ats}
        chosen = [overrides.pop(rule.id, rule) for rule in self.rules if rule.ats is None]
        chosen.extend(overrides.values())
        return chosen

    def update(self, rule_id: str, **changes: Any) -> ValidationRule:
        self._reload_if_changed()
        for index, rule in enumerate(self.rules):
            if rule.id == rule_id:
                updated = replace_fields(rule, **changes)
                self.rules[index] = updated
                self._save()
                return updated
        raise KeyError(f"Unknown rule: {rule_id}")

    def replace_all(self, rules: list[ValidationRule]) -> None:
        self.rules = rules
        self._save()

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(rule) for rule in self.rules], indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)


class MappingStore(JsonBacked):
    """JSON-backed mapping store with explicit approval and version history."""

    def __init__(self, path: str | Path = "mapping_store.json") -> None:
        self.path = Path(path)
        self._versions: list[MappingVersion] = []
        self._lock = threading.Lock()
        self._stamp: int | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            self._versions = []
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._versions = [
            MappingVersion(
                **{
                    **item,
                    "mappings": [FieldMapping(**mapping) for mapping in item["mappings"]],
                    "abstentions": item.get("abstentions", []),
                }
            )
            for item in data
        ]

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(item) for item in self._versions], indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)

    def list_partners(self) -> list[dict[str, Any]]:
        self._reload_if_changed()
        partners: list[dict[str, Any]] = []
        for ats, payload_type in {(version.ats, version.payload_type) for version in self._versions}:
            active = self.get(ats, payload_type)
            drafts = [version for version in self._versions if version.ats == ats and version.payload_type == payload_type and version.status == "draft"]
            partners.append({
                "ats": ats,
                "payload_type": payload_type,
                "version": active.version if active else None,
                "status": "approved" if active else "needs_mapping",
                "pending_drafts": len(drafts),
            })
        return partners

    def versions_for(self, ats: str, payload_type: str) -> list[MappingVersion]:
        self._reload_if_changed()
        return [version for version in self._versions if version.ats == ats and version.payload_type == payload_type]

    def next_version(self, ats: str, payload_type: str) -> int:
        self._reload_if_changed()
        versions = [v.version for v in self._versions if v.ats == ats and v.payload_type == payload_type]
        return max(versions, default=0) + 1

    def add_draft(
        self,
        ats: str,
        payload_type: str,
        mappings: list[FieldMapping],
        proposed_by: str = "system",
        abstentions: list[dict[str, str]] | None = None,
    ) -> MappingVersion:
        self._reload_if_changed()
        draft = MappingVersion(
            ats,
            payload_type,
            self.next_version(ats, payload_type),
            mappings,
            abstentions or [],
            proposed_by=proposed_by,
        )
        self._versions.append(draft)
        self._save()
        return draft

    def approve(
        self,
        ats: str,
        payload_type: str,
        version: int,
        reviewer: str,
        replay_payloads: Iterable[dict[str, Any]] = (),
        rules: Iterable[ValidationRule] = (),
    ) -> MappingVersion:
        selected = self.get(ats, payload_type, version)
        if selected is None:
            raise ValueError(f"Mapping version {version} does not exist")
        if selected.proposed_by == reviewer:
            raise ValueError("The mapping proposer cannot approve the same mapping")
        replay_failures = [
            result
            for payload in replay_payloads
            if (result := apply_mapping(selected, payload, rules)).status != "processed"
        ]
        if replay_failures:
            raise ValueError(f"Mapping failed replay validation for {len(replay_failures)} payload(s)")
        selected.status = "approved"
        selected.approved_by = reviewer
        selected.approved_at = utc_now()
        self._save()
        return selected

    def get(self, ats: str, payload_type: str, version: int | None = None) -> MappingVersion | None:
        self._reload_if_changed()
        matches = [v for v in self._versions if v.ats == ats and v.payload_type == payload_type]
        if version is not None:
            return next((v for v in matches if v.version == version), None)
        approved = [v for v in matches if v.status == "approved"]
        return max(approved, key=lambda item: item.version, default=None)


class MappingDraft:
    """Small deterministic draft generator used when no LLM adapter is configured."""

    def draft(self, payload: dict[str, Any], destination_fields: Iterable[str]) -> list[FieldMapping]:
        source_fields = self._flatten(payload)
        mappings = []
        for destination in destination_fields:
            destination_name = destination.rsplit(".", 1)[-1].lower()
            source = next((item for item in source_fields if item.rsplit(".", 1)[-1].lower() == destination_name), None)
            if source:
                mappings.append(FieldMapping(source, destination))
        return mappings

    def missing_fields(self, payload: dict[str, Any], destination_fields: Iterable[str]) -> list[str]:
        mapped = {mapping.destination for mapping in self.draft(payload, destination_fields)}
        return [destination for destination in destination_fields if destination not in mapped]

    def _flatten(self, value: dict[str, Any], prefix: str = "") -> list[str]:
        fields = []
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            fields.extend(self._flatten(child, path) if isinstance(child, dict) else [path])
        return fields


class Pipeline:
    def __init__(self, store: MappingStore, drift_tracker: DriftTracker | None = None) -> None:
        self.store = store
        self.drift_tracker = drift_tracker

    def process(
        self,
        ats: str,
        payload_type: str,
        payload: dict[str, Any] | str | bytes,
        rules: Iterable[ValidationRule] = (),
    ) -> ProcessingResult:
        payload = parse_input(payload)
        rules = list(rules)
        mapping = self.store.get(ats, payload_type)
        if mapping is None:
            return ProcessingResult("needs_mapping", {}, [{"field": "_mapping", "message": "No approved mapping exists"}], None)

        presence = presence_rules(rules)
        mapped: dict[str, Any] = {}
        issues: list[dict[str, str]] = []
        for item in mapping.mappings:
            value = static_value(item.source) if item.source.startswith("Static:") else get_path(payload, item.source, item.source_is_list)
            missing = value is None or (isinstance(value, str) and not value.strip())
            if item.source_is_list and value == []:
                try:
                    put_path(mapped, item.destination, [])
                except (TypeError, ValueError):
                    issues.append({"field": item.destination, "message": f"Source field is missing: {item.source}", "group": "Mapping"})
                continue
            if missing:
                if is_presence_required(item, presence):
                    issues.append({"field": item.destination, "message": f"Source field is missing: {item.source}", "group": "Mapping"})
                continue
            if isinstance(value, list) and not item.source_is_list:
                issues.append({
                    "field": item.destination,
                    "message": "Multiple source values found; set source_is_list=True for a stable list shape",
                    "group": "Mapping",
                })
                value = value[0]
            try:
                if destination_conflicts(mapped, item.destination):
                    issues.append({"field": item.destination, "message": "Destination path overlaps an existing mapping", "group": "Mapping"})
                    continue
                put_path(mapped, item.destination, transform_value(value, item.transform, item.equivalents))
            except (TypeError, ValueError) as error:
                issues.append({"field": item.destination, "message": str(error), "group": "Mapping"})

        issues.extend(self._validate(mapped, rules, {issue["field"] for issue in issues}))
        status = "exception" if issues else "processed"
        drift_alerts = self.drift_tracker.record(ats, payload_type, issues) if self.drift_tracker else []
        return ProcessingResult(status, mapped, issues, mapping.version, drift_alerts)

    def _validate(
        self,
        payload: dict[str, Any],
        rules: Iterable[ValidationRule],
        already_reported: set[str] | frozenset[str] = frozenset(),
    ) -> list[dict[str, str]]:
        """Check the mapped payload against the rules.

        Fields in ``already_reported`` failed at the mapping stage, which names the
        source field the partner did not send. Repeating "required field is missing"
        for them would report the same root cause twice.
        """
        issues: list[dict[str, str]] = []
        for rule in rules:
            if not rule.enabled:
                continue
            value = get_path(payload, rule.field)
            if value is None or value == [] or (isinstance(value, str) and not value.strip()):
                if rule.required and rule.field not in already_reported:
                    issues.append(_issue(rule, f"Required field is missing: {rule.description or rule.id}"))
                continue
            for item in value if isinstance(value, list) else [value]:
                issues.extend(self._check_value(rule, item))
        return issues

    def _check_value(self, rule: ValidationRule, value: Any) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        text = value if isinstance(value, str) else str(value)
        if rule.allowed_values and text not in rule.allowed_values:
            issues.append(_issue(rule, f"{text!r} is not one of: {', '.join(rule.allowed_values)}"))
        if rule.pattern and re.fullmatch(rule.pattern, text) is None:
            issues.append(_issue(rule, f"{text!r} does not match {rule.description or rule.id}"))
        if rule.check:
            checker = BUSINESS_CHECKS.get(rule.check)
            if checker is None:
                issues.append(_issue(rule, f"Unknown check: {rule.check}"))
            else:
                problem = checker(text)
                if problem:
                    issues.append(_issue(rule, problem))
        return issues


def _issue(rule: ValidationRule, message: str) -> dict[str, str]:
    return {"field": rule.field, "message": message, "rule_id": rule.id, "group": rule.group}


def presence_rules(rules: Iterable[ValidationRule]) -> dict[str, bool]:
    """Which destinations have a rule speaking for presence, and its answer.

    Only Completeness rules say whether a field has to be there. A Format or
    Business rule constrains the value when one is present and says nothing
    about whether it must be - reading those as "optional" would quietly stop
    required fields being reported.

    A destination with several Completeness rules is required if any enabled
    one says so.
    """
    presence: dict[str, bool] = {}
    for rule in rules:
        if rule.enabled and rule.group == "Completeness":
            presence[rule.field] = presence.get(rule.field, False) or rule.required
    return presence


def is_presence_required(item: FieldMapping, presence: dict[str, bool]) -> bool:
    """Whether a missing source value is worth reporting.

    A validation rule covering the destination is the authority, so the
    "must be present" toggle on the Validation screen genuinely governs
    presence. Without that, a field marked required on the mapping would
    fail whatever the toggle said, and the toggle would look broken.
    Destinations no rule covers keep the mapping's own required flag.
    """
    if item.destination in presence:
        return presence[item.destination]
    return item.required or not item.source_is_list


def static_value(source: str) -> str:
    return source.removeprefix("Static:")


def destination_conflicts(payload: dict[str, Any], path: str) -> bool:
    parts = parse_path(path)
    target: Any = payload
    for index, part in enumerate(parts):
        if isinstance(part, int):
            if not isinstance(target, list) or part >= len(target):
                return False
            target = target[part]
        else:
            if not isinstance(target, dict) or part not in target:
                return False
            target = target[part]
        if index < len(parts) - 1 and not isinstance(target, (dict, list)):
            return True
    return True


def transform_value(value: Any, transform: str | None, equivalents: dict[str, str] | None = None) -> Any:
    if isinstance(value, list):
        return [transform_value(item, transform, equivalents) for item in value]
    if isinstance(value, str) and equivalents and value in equivalents:
        value = equivalents[value]
    if transform is None or transform == "identity":
        return value
    if transform == "trim":
        return value.strip() if isinstance(value, str) else value
    if transform == "digits_only":
        return re.sub(r"\D", "", str(value))
    if transform == "phone":
        digits = re.sub(r"\D", "", str(value))
        return f"+{digits}" if not digits.startswith("+") else digits
    if transform == "date":
        if not isinstance(value, str):
            raise ValueError("Date transform requires a string")
        for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(value.strip(), pattern).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"Could not parse date: {value}")
    raise ValueError(f"Unknown transform: {transform}")


class _SingleMappingStore:
    def __init__(self, mapping: MappingVersion) -> None:
        self._mapping = MappingVersion(
            mapping.ats, mapping.payload_type, mapping.version, mapping.mappings,
            mapping.abstentions, status="approved", proposed_by=mapping.proposed_by,
            approved_by=mapping.approved_by, approved_at=mapping.approved_at,
            created_at=mapping.created_at,
        )

    def get(self, ats: str, payload_type: str, version: int | None = None) -> MappingVersion:
        return self._mapping


def apply_mapping(mapping: MappingVersion, payload: dict[str, Any], rules: Iterable[ValidationRule] = ()) -> ProcessingResult:
    return Pipeline(_SingleMappingStore(mapping)).process(mapping.ats, mapping.payload_type, payload, rules)


class LLMMappingDraft:
    """Adapter boundary for an LLM that can explicitly abstain from a field."""

    def __init__(self, proposer: Any) -> None:
        self.proposer = proposer
        self.abstentions: list[dict[str, str]] = []
        self._last_payload: dict[str, Any] | None = None
        self._last_destination_fields: tuple[str, ...] = ()
        self._last_mappings: list[FieldMapping] = []

    def draft(self, payload: dict[str, Any], destination_fields: Iterable[str]) -> list[FieldMapping]:
        destinations = tuple(destination_fields)
        proposals = self.proposer(payload, list(destinations))
        self.abstentions = []
        result = []
        for proposal in proposals:
            if proposal.get("source") in (None, "", "MISSING"):
                self.abstentions.append({
                    "destination": proposal["destination"],
                    "reason": proposal.get("reason", "The source field was not found in the payload"),
                })
                continue
            result.append(FieldMapping(
                proposal["source"],
                proposal["destination"],
                bool(proposal.get("required", False)),
                proposal.get("transform"),
                proposal.get("equivalents", {}),
                bool(proposal.get("source_is_list", False)),
            ))
        self._last_payload = payload
        self._last_destination_fields = destinations
        self._last_mappings = result
        return result

    def missing_fields(self, payload: dict[str, Any], destination_fields: Iterable[str]) -> list[dict[str, str]]:
        destinations = tuple(destination_fields)
        if payload is not self._last_payload or destinations != self._last_destination_fields:
            self.draft(payload, destinations)
        mappings = self._last_mappings
        destinations = {proposal["destination"] for proposal in self.abstentions}
        mapped = {mapping.destination for mapping in mappings}
        return [
            {"field": destination, "reason": next(item["reason"] for item in self.abstentions if item["destination"] == destination)}
            for destination in destinations - mapped
        ]


class DriftTracker(JsonBacked):
    """Raises drift only after repeated field failures cross a threshold."""

    def __init__(self, threshold: int = 3, path: str | Path = "drift_counts.json") -> None:
        self.threshold = threshold
        self.path = Path(path)
        self._lock = threading.Lock()
        self.failures: dict[tuple[str, str, str], int] = {}
        self._stamp: int | None = None
        self._load()

    def _load(self) -> None:
        self._stamp = file_stamp(self.path)
        if not self.path.exists():
            self.failures = {}
            return
        self.failures = json.loads(self.path.read_text(encoding="utf-8"))

    def record(self, ats: str, payload_type: str, issues: Iterable[dict[str, str]]) -> list[dict[str, str]]:
        self._reload_if_changed()
        alerts = []
        had_issues = False
        for issue in issues:
            had_issues = True
            key = f"{ats}|{payload_type}|{issue['field']}"
            self.failures[key] = self.failures.get(key, 0) + 1
            if self.failures[key] >= self.threshold:
                alerts.append({"field": issue["field"], "message": "Payload drift threshold exceeded"})
        if had_issues:
            self._save()
        return alerts

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.failures, indent=2), encoding="utf-8")
        self._stamp = file_stamp(self.path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an approved ATS mapping pipeline")
    parser.add_argument("payload", type=Path)
    parser.add_argument("--ats", required=True)
    parser.add_argument("--payload-type", required=True)
    parser.add_argument("--store", type=Path, default=Path("mapping_store.json"))
    args = parser.parse_args()
    result = Pipeline(MappingStore(args.store)).process(args.ats, args.payload_type, args.payload.read_bytes())
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.status == "processed" else 1


if __name__ == "__main__":
    sys.exit(main())