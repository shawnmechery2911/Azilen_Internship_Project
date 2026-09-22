import io
import os
import unittest
from dataclasses import replace
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline import (
    DriftTracker,
    ExceptionQueue,
    FieldMapping,
    LLMMappingDraft,
    MappingDraft,
    MappingStore,
    PayloadShape,
    Pipeline,
    AiUsageLog,
    RuleBindingStore,
    SamplePayloadStore,
    ValidationRule,
    ValidationRuleStore,
    parse_input,
)
from bedrock_proposer import BedrockProposer, describe_paths


class PipelineTests(unittest.TestCase):
    def test_requires_human_approval(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "candidate.given_name")])
            result = Pipeline(store).process("ats", "candidate", {"first": "Ada"})
            self.assertEqual(result.status, "needs_mapping")

    def test_processes_approved_mapping_and_records_version(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "candidate.given_name", True)])
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"first": "Ada"})
            self.assertEqual(result.status, "processed")
            self.assertEqual(result.mapping_version, 1)
            self.assertEqual(result.mapped_payload, {"candidate": {"given_name": "Ada"}})

    def test_validation_and_exception_queue(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("email", "candidate.email")])
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process(
                "ats", "candidate", {"email": "invalid"}, [ValidationRule("email_format", "candidate.email", pattern=r"[^@]+@[^@]+")]
            )
            self.assertEqual(result.status, "exception")
            queue = ExceptionQueue(Path(folder) / "exceptions.json")
            record = queue.add("ats", "candidate", {"email": "invalid"}, result)
            self.assertEqual(queue.close(record.id).status, "closed")

    def test_draft_matches_nested_field_names(self):
        mappings = MappingDraft().draft({"person": {"first_name": "Ada"}}, ["candidate.first_name"])
        self.assertEqual(mappings, [FieldMapping("person.first_name", "candidate.first_name")])

    def test_arrays_static_values_and_transforms(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "order", [
                FieldMapping("first", "Applicant.Names[0].GivenName", True),
                FieldMapping("Static:1.0", "Version", True),
                FieldMapping("dob", "Applicant.DateOfBirth", transform="date"),
            ], proposed_by="author")
            store.approve("ats", "order", 1, "reviewer")
            result = Pipeline(store).process("ats", "order", {"first": "Ada", "dob": "9/15/1975"})
            self.assertEqual(result.status, "processed")
            self.assertEqual(result.mapped_payload["Applicant"]["Names"][0]["GivenName"], "Ada")
            self.assertEqual(result.mapped_payload["Version"], "1.0")
            self.assertEqual(result.mapped_payload["Applicant"]["DateOfBirth"], "1975-09-15")

    def test_xml_is_normalized_at_boundary(self):
        payload = parse_input("<Root><Person><Name>Ada</Name></Person><Tag>x</Tag><Tag>y</Tag></Root>")
        self.assertEqual(payload["Person"]["Name"], "Ada")
        self.assertEqual(payload["Tag"], ["x", "y"])

    def test_broken_json_is_reported_as_json_not_xml(self):
        """XML is the fallback, so its error used to be the one that surfaced:
        a JSON file came back "not well-formed: line 1, column 0", which names
        the wrong format and sends you to the wrong line."""
        # a single quote escaped the way a shell escapes it, not the way JSON does
        with self.assertRaises(ValueError) as caught:
            parse_input('{"degree": "Bachelor\'\\\'\'s"}')
        message = str(caught.exception)
        self.assertIn("Invalid JSON", message)
        self.assertIn("line 1", message)
        self.assertNotIn("well-formed", message)

    def test_repeated_list_paths_are_read(self):
        payload = {"Person": {"AddressHistory": {"Address": [{"City": "London"}, {"City": "Paris"}]}}}
        self.assertEqual(parse_input(json.dumps(payload))["Person"]["AddressHistory"]["Address"][1]["City"], "Paris")

    def test_replay_blocks_broken_mapping_and_proposer_cannot_approve(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "given", True)], proposed_by="author")
            with self.assertRaises(ValueError):
                store.approve("ats", "candidate", 1, "author")
            with self.assertRaises(ValueError):
                store.approve("ats", "candidate", 1, "reviewer", replay_payloads=[{}])

    def test_replay_allows_valid_mapping(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "given", True)], proposed_by="author")
            approved = store.approve("ats", "candidate", 1, "reviewer", replay_payloads=[{"first": "Ada"}])
            self.assertEqual(approved.status, "approved")

    def test_approve_applies_validation_rules_not_just_structure(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            rules = [ValidationRule("email_format", "Applicant.Email", "Format", "an email address", pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+")]
            store.add_draft("ats", "candidate", [FieldMapping("Person.Email", "Applicant.Email")], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer", [], rules)

            store.add_draft("ats", "candidate", [FieldMapping("Person.LastName", "Applicant.Email")], proposed_by="author")
            payloads = [{"Person": {"Email": "ada@example.com", "LastName": "Lovelace"}}]

            with self.assertRaises(ValueError):
                store.approve("ats", "candidate", 2, "reviewer", payloads, rules)

    def test_samples_are_kept_for_replay_and_deduplicated(self):
        with TemporaryDirectory() as folder:
            store = SamplePayloadStore(Path(folder) / "samples.json")
            store.remember("acme", {"a": 1})
            store.remember("acme", {"a": 1})          # same order twice
            store.remember("acme", {"b": 2})
            store.remember("other", {"c": 3})
            self.assertEqual(store.for_ats("acme"), [{"a": 1}, {"b": 2}])
            self.assertEqual(store.for_ats("other"), [{"c": 3}])
            self.assertEqual(store.for_ats("nobody"), [])

    def test_a_rename_retires_orders_written_in_the_old_shape(self):
        """They describe a payload that will not arrive again, so they are not
        evidence about the mapping that replaces it."""
        with TemporaryDirectory() as folder:
            store = SamplePayloadStore(Path(folder) / "samples.json")
            store.remember("acme", {"Person": {"ApplicantID": "A1"}})
            store.remember("acme", {"Person": {"ApplicantID": "A2"}})
            retired = store.retire("acme", "Person.ApplicantID", "Person.CandidateID")
            self.assertEqual(retired, 2)
            self.assertEqual(store.for_ats("acme"), [])

    def test_an_order_already_in_the_new_shape_is_kept(self):
        """The partner has started sending it, which is exactly what the new
        mapping should be held to."""
        with TemporaryDirectory() as folder:
            store = SamplePayloadStore(Path(folder) / "samples.json")
            store.remember("acme", {"Person": {"ApplicantID": "old"}})
            store.remember("acme", {"Person": {"CandidateID": "new"}})
            retired = store.retire("acme", "Person.ApplicantID", "Person.CandidateID")
            self.assertEqual(retired, 1)
            self.assertEqual(store.for_ats("acme"), [{"Person": {"CandidateID": "new"}}])

    def test_retiring_leaves_unrelated_partners_alone(self):
        with TemporaryDirectory() as folder:
            store = SamplePayloadStore(Path(folder) / "samples.json")
            store.remember("acme", {"Person": {"ApplicantID": "A1"}})
            store.remember("other", {"Person": {"ApplicantID": "B1"}})
            store.retire("acme", "Person.ApplicantID", "Person.CandidateID")
            self.assertEqual(store.for_ats("other"), [{"Person": {"ApplicantID": "B1"}}])

    def test_the_sample_corpus_is_capped(self):
        """It guards approvals rather than archiving traffic, so it is read on
        every approval and must not grow without bound."""
        with TemporaryDirectory() as folder:
            store = SamplePayloadStore(Path(folder) / "samples.json", limit=3)
            for n in range(6):
                store.remember("acme", {"n": n})
            kept = store.for_ats("acme")
            self.assertEqual(len(kept), 3)
            self.assertEqual(kept, [{"n": 3}, {"n": 4}, {"n": 5}])

    def test_a_draft_row_can_be_corrected_before_approval(self):
        """The model proposed a defensible but wrong source; a reviewer fixes
        it rather than rejecting the whole mapping."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [
                FieldMapping("PartnerSystem", "Sender.Id"),
            ], proposed_by="bedrock")
            store.edit_draft("ats", "candidate", 1, "Sender.Id", source="Username", required=True, edited_by="ops-lead")
            row = next(r for r in store.get("ats", "candidate", 1).mappings if r.destination == "Sender.Id")
            self.assertEqual(row.source, "Username")
            self.assertTrue(row.required)
            self.assertEqual(store.get("ats", "candidate", 1).edited_by, ["ops-lead"])

    def test_editing_a_draft_can_map_something_the_model_declined(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [], proposed_by="bedrock",
                            abstentions=[{"destination": "Applicant.SSN", "reason": "not present"}])
            store.edit_draft("ats", "candidate", 1, "Applicant.SSN", source="Person.Ssn", edited_by="ops-lead")
            draft = store.get("ats", "candidate", 1)
            self.assertEqual([r.source for r in draft.mappings], ["Person.Ssn"])
            self.assertEqual(draft.abstentions, [])

    def test_a_row_can_be_removed_from_a_draft(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [
                FieldMapping("Username", "Applicant.PartnerReference1"),
                FieldMapping("Person.Email", "Applicant.Email"),
            ], proposed_by="bedrock")
            store.edit_draft("ats", "candidate", 1, "Applicant.PartnerReference1", remove=True, edited_by="ops-lead")
            left = [r.destination for r in store.get("ats", "candidate", 1).mappings]
            self.assertEqual(left, ["Applicant.Email"])

    def test_an_approved_mapping_cannot_be_edited_in_place(self):
        """Production runs it and earlier orders were mapped with it, so a
        change has to be a new version the guardrail can review."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("a", "A")], proposed_by="bedrock")
            store.approve("ats", "candidate", 1, "reviewer")
            with self.assertRaises(ValueError):
                store.edit_draft("ats", "candidate", 1, "A", source="b", edited_by="ops-lead")

    def test_ai_usage_notices_the_store_being_cleared(self):
        """Reading .records directly skipped the reload check, so the usage
        panel kept reporting calls from a file that no longer existed."""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "ai_usage.json"
            log = AiUsageLog(path)
            log.add("acme", "candidate", "a-model", {"inputTokens": 10, "outputTokens": 5})
            self.assertEqual(len(log.all()), 1)
            path.unlink()
            self.assertEqual(log.all(), [])
            self.assertEqual(log.recent(), [])

    def approved(self, folder, rows):
        store = MappingStore(Path(folder) / "mappings.json")
        store.add_draft("ats", "candidate", rows, proposed_by="bedrock")
        store.approve("ats", "candidate", 1, "reviewer")
        return store

    def test_a_field_that_stops_arriving_is_drift(self):
        """Not an order failing - the partner no longer sending something they
        have sent every time until now."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            for _ in range(3):
                pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            result = pipeline.process("ats", "candidate", {"Person": {}})
            kinds = {(a["kind"], a["field"]) for a in result.drift_alerts}
            self.assertIn(("removed", "Person.ApplicantID"), kinds)

    def test_a_renamed_field_is_reported_as_a_rename(self):
        """Gone and arrived in the same payload. Reported as two unrelated
        facts it is a puzzle; reported as a rename it is a fix."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            for _ in range(3):
                pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            result = pipeline.process("ats", "candidate", {"Person": {"CandidateID": "A1"}})
            rename = next(a for a in result.drift_alerts if a["kind"] == "renamed")
            self.assertEqual(rename["field"], "Person.ApplicantID")
            self.assertEqual(rename["became"], "Person.CandidateID")

    def test_a_renamed_top_level_field_is_reported_as_a_rename(self):
        """The same rename one level up. rsplit on a path with no dot returns
        the path itself, so two top-level fields read as living in different
        objects and this came back as an unrelated removal plus an addition -
        no rename, and so no one-click remap, for the commonest case there is."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("first_name", "Applicant.Names[0].GivenName", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            for _ in range(3):
                pipeline.process("ats", "candidate", {"first_name": "Katherine"})
            result = pipeline.process("ats", "candidate", {"given_name": "Katherine"})
            rename = next(a for a in result.drift_alerts if a["kind"] == "renamed")
            self.assertEqual(rename["field"], "first_name")
            self.assertEqual(rename["became"], "given_name")

    def test_a_new_field_is_drift_even_when_nothing_fails(self):
        """A partner who starts sending a phone number breaks nothing, and it
        is still the thing you want to know."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            for _ in range(3):
                pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            result = pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1", "Phone": "0123456789"}})
            self.assertEqual(result.status, "processed")
            added = next(a for a in result.drift_alerts if a["kind"] == "added")
            self.assertEqual(added["field"], "Person.Phone")

    def test_drift_keeps_reporting_until_the_mapping_is_updated(self):
        """Folding a drifted payload into the baseline would make the old field
        look merely optional, and the alert would disappear because nobody
        acted on it."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            for _ in range(3):
                pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            renamed = {"Person": {"CandidateID": "A1"}}
            for _ in range(3):
                result = pipeline.process("ats", "candidate", renamed)
                self.assertTrue(any(a["kind"] == "renamed" for a in result.drift_alerts))

            # remap, and the same payload stops being news
            store.add_draft("ats", "candidate", [FieldMapping("Person.CandidateID", "Applicant.ApplicantId", True)], proposed_by="drift")
            store.approve("ats", "candidate", 2, "reviewer")
            after = pipeline.process("ats", "candidate", renamed)
            self.assertEqual(after.drift_alerts, [])
            self.assertEqual(after.status, "processed")

    def test_a_field_that_comes_and_goes_is_not_drift(self):
        """It was never a promise, and alerting on it is how an alert becomes
        noise nobody reads."""
        with TemporaryDirectory() as folder:
            store = self.approved(folder, [FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", True)])
            shapes = PayloadShape(Path(folder) / "shapes.json")
            pipeline = Pipeline(store, shapes=shapes)
            pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1", "Middle": "Q"}})
            pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            result = pipeline.process("ats", "candidate", {"Person": {"ApplicantID": "A1"}})
            self.assertEqual([a for a in result.drift_alerts if a["field"] == "Person.Middle"], [])

    def test_drift_requires_repeated_failures(self):
        with TemporaryDirectory() as folder:
            tracker = DriftTracker(threshold=2, path=Path(folder) / "drift.json")
            issue = [{"field": "first", "message": "missing"}]
            self.assertEqual(tracker.record("ats", "candidate", issue), [])
            self.assertEqual(len(tracker.record("ats", "candidate", issue)), 1)

    def test_a_field_that_recovers_stops_being_drift(self):
        """The count only went up, so a field that crossed the threshold once
        carried a red badge on every later exception for good - including
        after the mapping that broke it had been fixed."""
        with TemporaryDirectory() as folder:
            tracker = DriftTracker(threshold=2, path=Path(folder) / "drift.json")
            issue = [{"field": "first", "message": "missing"}]
            tracker.record("ats", "candidate", issue)
            self.assertEqual(len(tracker.record("ats", "candidate", issue)), 1)

            tracker.record("ats", "candidate", [])       # one clean order
            self.assertEqual(tracker.failures, {})
            # and it now has to earn the threshold again
            self.assertEqual(tracker.record("ats", "candidate", issue), [])

    def test_a_field_still_failing_keeps_its_count(self):
        """Recovery is per field. One field coming good must not clear the
        one next to it that is still broken."""
        with TemporaryDirectory() as folder:
            tracker = DriftTracker(threshold=2, path=Path(folder) / "drift.json")
            both = [{"field": "first", "message": "missing"}, {"field": "last", "message": "missing"}]
            tracker.record("ats", "candidate", both)
            alerts = tracker.record("ats", "candidate", [{"field": "last", "message": "missing"}])
            self.assertEqual([a["field"] for a in alerts], ["last"])
            self.assertNotIn("ats|candidate|first", tracker.failures)
            # and another partner is never touched by either
            tracker.record("other", "candidate", both)
            tracker.record("ats", "candidate", [])
            self.assertIn("other|candidate|first", tracker.failures)

    def test_a_drift_alert_names_the_field_and_the_count(self):
        with TemporaryDirectory() as folder:
            tracker = DriftTracker(threshold=2, path=Path(folder) / "drift.json")
            issue = [{"field": "Applicant.Email", "message": "missing"}]
            tracker.record("ats", "candidate", issue)
            alert = tracker.record("ats", "candidate", issue)[0]
            self.assertIn("Applicant.Email", alert["message"])
            self.assertIn("2", alert["message"])
            self.assertNotIn("threshold", alert["message"])

    def test_llm_adapter_can_abstain(self):
        adapter = LLMMappingDraft(lambda payload, fields: [
            {"destination": "given", "source": "first"},
            {"destination": "ssn", "source": "MISSING", "reason": "SSN is not present"},
        ])
        self.assertEqual(adapter.draft({"first": "Ada"}, ["given", "ssn"]), [FieldMapping("first", "given")])
        self.assertEqual(adapter.missing_fields({"first": "Ada"}, ["given", "ssn"]), [{"field": "ssn", "reason": "SSN is not present"}])

    def test_llm_missing_fields_uses_cached_draft(self):
        calls = 0

        def proposer(payload, fields):
            nonlocal calls
            calls += 1
            return [{"destination": "ssn", "source": "MISSING", "reason": "SSN is not present"}]

        adapter = LLMMappingDraft(proposer)
        payload = {"first": "Ada"}
        adapter.draft(payload, ["ssn"])
        self.assertEqual(adapter.missing_fields(payload, ["ssn"]), [{"field": "ssn", "reason": "SSN is not present"}])
        self.assertEqual(calls, 1)

    def test_overlapping_destinations_are_reported(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "A.B"), FieldMapping("last", "A.B.C")], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"first": "Ada", "last": "Lovelace"})
            self.assertEqual(result.status, "exception")
            self.assertTrue(any("overlaps" in issue["message"] for issue in result.issues))

    def test_list_mapping_has_stable_shape(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("addresses.City", "cities", source_is_list=True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            one = Pipeline(store).process("ats", "candidate", {"addresses": [{"City": "London"}]})
            none = Pipeline(store).process("ats", "candidate", {"addresses": []})
            self.assertEqual(one.mapped_payload["cities"], ["London"])
            self.assertEqual(none.mapped_payload["cities"], [])

    def test_unmarked_multiple_values_are_reported(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("addresses.City", "city")], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"addresses": [{"City": "London"}, {"City": "Paris"}]})
            self.assertEqual(result.status, "exception")
            self.assertEqual(result.mapped_payload["city"], "London")
            self.assertTrue(any("source_is_list=True" in issue["message"] for issue in result.issues))

    def test_empty_required_value_is_an_issue(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("middle", "middle", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"middle": "   "})
            self.assertEqual(result.status, "exception")

    def test_a_missing_source_is_reported_once_not_twice(self):
        """A field the partner never sent fails at the mapping stage. The
        completeness rule for the same field must not repeat it — the mapping
        issue already names the source field that is missing."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.Email", "Applicant.Email", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            rules = [ValidationRule("email_required", "Applicant.Email", "Completeness", "an email", required=True)]
            result = Pipeline(store).process("ats", "candidate", {"Person": {}}, rules)
            email_issues = [issue for issue in result.issues if issue["field"] == "Applicant.Email"]
            self.assertEqual(len(email_issues), 1)
            self.assertEqual(email_issues[0]["group"], "Mapping")
            self.assertIn("Person.Email", email_issues[0]["message"])

    def test_a_required_field_the_mapping_ignores_is_still_reported(self):
        """The dedupe must not hide a genuine completeness failure: if nothing
        maps to a required destination at all, there is no mapping issue to
        stand in for it."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.First", "Applicant.GivenName")], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            rules = [ValidationRule("email_required", "Applicant.Email", "Completeness", "an email", required=True)]
            result = Pipeline(store).process("ats", "candidate", {"Person": {"First": "Ada"}}, rules)
            self.assertEqual([issue["field"] for issue in result.issues], ["Applicant.Email"])
            self.assertEqual(result.issues[0]["group"], "Completeness")

    def test_the_required_toggle_beats_the_mappings_own_required_flag(self):
        """The Validation screen's "must be present" toggle has to win, or it
        looks broken: the field is required on the mapping too, and that check
        used to fire whatever the rule said."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.SSN", "Applicant.SSN", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            pipeline = Pipeline(store)
            # bound=True is what rules_for sets when a partner has actually
            # been bound to a rule; an unbound rule is only a default.
            rule = ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "an SSN", required=True, bound=True)

            demanded = pipeline.process("ats", "candidate", {"Person": {}}, [rule])
            self.assertEqual(demanded.status, "exception")
            self.assertEqual([i["field"] for i in demanded.issues], ["Applicant.SSN"])

            relaxed = pipeline.process("ats", "candidate", {"Person": {}}, [replace(rule, required=False)])
            self.assertEqual(relaxed.status, "processed")
            self.assertEqual(relaxed.issues, [])

    def test_an_unbound_rule_does_not_overrule_the_approver(self):
        """The approver marked this field required while looking at the
        partner's payload. A catalogue rule nobody bound this partner to is a
        default, not a decision, and must not quietly relax it."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.Email", "Applicant.Email", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            unbound = ValidationRule("email_present", "Applicant.Email", "Completeness", "an email", required=False)
            result = Pipeline(store).process("ats", "candidate", {"Person": {}}, [unbound])
            self.assertEqual(result.status, "exception")
            self.assertEqual([i["field"] for i in result.issues], ["Applicant.Email"])

    def test_a_field_no_rule_covers_keeps_the_mapping_flag(self):
        """Turning presence over to the rules must not make uncovered fields
        silently optional."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.First", "Applicant.GivenName", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            unrelated = ValidationRule("email_present", "Applicant.Email", "Completeness", "an email", required=False)
            result = Pipeline(store).process("ats", "candidate", {"Person": {}}, [unrelated])
            self.assertEqual(result.status, "exception")
            self.assertEqual([i["field"] for i in result.issues], ["Applicant.GivenName"])

    def test_a_format_rule_does_not_make_a_required_field_optional(self):
        """A Format rule constrains the value when there is one. It must not be
        read as saying the field may be absent - that silently stopped
        FCRAPermissibleType being reported on the incomplete fixture."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.Purpose", "FCRAPermissibleType", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            fmt = ValidationRule("purpose_enum", "FCRAPermissibleType", "Format", "a purpose", allowed_values=("Volunteer",))
            result = Pipeline(store).process("ats", "candidate", {"Person": {}}, [fmt])
            self.assertEqual(result.status, "exception")
            self.assertEqual([i["field"] for i in result.issues], ["FCRAPermissibleType"])

    def test_a_disabled_presence_rule_does_not_govern(self):
        """A rule switched off entirely should not quietly relax the mapping."""
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.SSN", "Applicant.SSN", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            off = ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "an SSN", required=True, enabled=False)
            result = Pipeline(store).process("ats", "candidate", {"Person": {}}, [off])
            self.assertEqual(result.status, "exception")

    def test_drift_tracker_is_wired_into_processing(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "given", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            pipeline = Pipeline(store, DriftTracker(threshold=2, path=Path(folder) / "drift.json"))
            self.assertEqual(pipeline.process("ats", "candidate", {}).drift_alerts, [])
            self.assertEqual(len(pipeline.process("ats", "candidate", {}).drift_alerts), 1)

    def test_make_adapter_reports_fallback(self):
        original_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        original_model = os.environ.get("BEDROCK_MODEL_ID")
        try:
            os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
            os.environ.pop("BEDROCK_MODEL_ID", None)
            with redirect_stdout(io.StringIO()) as stream:
                adapter = __import__("bedrock_proposer").make_adapter()
            self.assertIsInstance(adapter, MappingDraft)
            self.assertIn("offline name matcher", stream.getvalue().lower())
        finally:
            if original_token is not None:
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = original_token
            if original_model is not None:
                os.environ["BEDROCK_MODEL_ID"] = original_model

    def test_mapping_store_lists_versions(self):
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [FieldMapping("first", "given")], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            store.add_draft("ats", "candidate", [FieldMapping("last", "family")], proposed_by="author")
            partner = store.list_partners()[0]
            self.assertEqual(partner["ats"], "ats")
            self.assertEqual(partner["version"], 1)
            self.assertEqual(partner["status"], "approved")
            self.assertEqual(partner["pending_drafts"], 1)

    def test_fixture_order_mapping_works(self):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        data = json.loads((fixtures_dir / "ideallogic-order.json").read_text(encoding="utf-8"))
        mapping_rows = json.loads((fixtures_dir / "ideallogic-mapping.json").read_text(encoding="utf-8"))
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "tmp-mappings.json")
            mappings = [FieldMapping(**row) for row in mapping_rows]
            store.add_draft("demo-ats", "candidate", mappings, proposed_by="demo")
            store.approve("demo-ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("demo-ats", "candidate", data)
        self.assertEqual(result.status, "exception")
        self.assertEqual(result.mapped_payload["Applicant"]["Names"][0]["GivenName"], "StefTest")
        self.assertEqual(result.mapped_payload["Version"], "1.0")
        # SSN is marked required in the fixture and this order does not carry
        # one. TransactInfo.TransactId is marked optional and is absent too,
        # and used to be reported anyway - it must not be now.
        reported = [issue["field"] for issue in result.issues]
        self.assertIn("Applicant.SSN", reported)
        self.assertNotIn("TransactInfo.TransactId", reported)

    def test_draft_endpoint_returns_abstentions(self):
        import api

        class StubAdapter:
            def __init__(self):
                self.abstentions = [{"destination": "ssn", "reason": "not present"}]

            def draft(self, payload, destination_fields):
                self.last_payload = payload
                self.last_fields = destination_fields
                return [{"destination": "given", "source": "person.first", "required": True, "reason": "match"}]

        adapter = StubAdapter()
        with TemporaryDirectory() as folder:
            with patch.object(api, "store", MappingStore(Path(folder) / "mappings.json")), \
                 patch.object(api, "ai_log", __import__("pipeline").AiUsageLog(Path(folder) / "ai_usage.json")), \
                 patch.object(api, "rules_store", ValidationRuleStore(Path(folder) / "rules.json")), \
                 patch.object(api, "queue", ExceptionQueue(Path(folder) / "exceptions.json")), \
                 patch.object(api, "samples", SamplePayloadStore(Path(folder) / "samples.json")), \
                 patch("api.make_adapter", return_value=adapter):
                client = TestClient(api.app)
                response = client.post(
                    "/api/mappings/demo-ats/candidate/draft",
                    json={"payload": {"person": {"first": "Ada"}}, "destination_fields": ["given", "ssn"]},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["abstentions"][0]["destination"], "ssn")

    def test_approval_answers_presence_from_the_mapping(self):
        """The mapping already says which fields the partner sends and which
        are always there. Asking the same question again as twenty switches is
        how a partner ends up demanding nothing."""
        import api

        with TemporaryDirectory() as folder:
            rules = ValidationRuleStore(Path(folder) / "rules.json")
            rules.replace_all([
                ValidationRule("given", "given", "Completeness", "a first name"),
                ValidationRule("middle", "middle", "Completeness", "a middle name"),
                ValidationRule("ssn", "ssn", "Completeness", "an SSN"),
                ValidationRule("given_shape", "given", "Format", "letters", pattern=r"\w+"),
            ])
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate", [
                FieldMapping("person.first", "given", required=True),
                FieldMapping("person.middle", "middle"),   # sent, but often empty
            ], proposed_by="author")
            with patch.object(api, "store", store), \
                 patch.object(api, "rules_store", rules), \
                 patch.object(api, "bindings", binds), \
                 patch.object(api, "samples", SamplePayloadStore(Path(folder) / "samples.json")):
                client = TestClient(api.app)
                response = client.post(
                    "/api/mappings/ats/candidate/1/approve", json={"reviewer": "someone-else"}
                )
                self.assertEqual(response.status_code, 200)
                applied = {r.id: r for r in binds.rules_for("ats", rules.all())}

            # mapped and always there -> demanded
            self.assertTrue(applied["given"].required)
            # mapped but optional -> bound, and explicitly not demanded, because
            # a missing middle name must not turn an ordinary order into an
            # exception
            self.assertTrue(applied["middle"].bound)
            self.assertFalse(applied["middle"].required)
            # never mapped -> left alone entirely
            self.assertFalse(applied["ssn"].bound)
            # and a Format rule is none of this rule's business
            self.assertFalse(applied["given_shape"].bound)

    def test_approving_again_keeps_choices_made_by_hand(self):
        import api

        with TemporaryDirectory() as folder:
            rules = ValidationRuleStore(Path(folder) / "rules.json")
            rules.replace_all([ValidationRule("given", "given", "Completeness", "a first name")])
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("ats", "given", enabled=True, required=False)  # switched off on purpose
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("ats", "candidate",
                            [FieldMapping("person.first", "given", required=True)], proposed_by="author")
            with patch.object(api, "store", store), \
                 patch.object(api, "rules_store", rules), \
                 patch.object(api, "bindings", binds), \
                 patch.object(api, "samples", SamplePayloadStore(Path(folder) / "samples.json")):
                TestClient(api.app).post(
                    "/api/mappings/ats/candidate/1/approve", json={"reviewer": "someone-else"}
                )
            applied = {r.id: r for r in binds.rules_for("ats", rules.all())}
            self.assertFalse(applied["given"].required)

    def test_the_api_refuses_to_widen_a_rule(self):
        """Silently dropping a stray value would leave someone believing the
        partner accepts it, so the request fails and says why."""
        import api

        with TemporaryDirectory() as folder:
            rules = ValidationRuleStore(Path(folder) / "rules.json")
            rules.replace_all([
                ValidationRule("fcra", "FCRAPermissibleType", "Format", "a purpose",
                               allowed_values=("Volunteer", "Tenant Screening")),
                ValidationRule("ssn", "Applicant.SSN", "Completeness", "an SSN"),
            ])
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            with patch.object(api, "rules_store", rules), patch.object(api, "bindings", binds):
                client = TestClient(api.app)
                path = "/api/partners/vsys/validation-rules/fcra"

                narrow = client.patch(path, json={"allowed_values": ["Volunteer"]})
                self.assertEqual(narrow.status_code, 200)
                self.assertEqual(narrow.json()["allowed_values"], ["Volunteer"])

                widen = client.patch(path, json={"allowed_values": ["Volunteer", "Something Else"]})
                self.assertEqual(widen.status_code, 400)
                self.assertIn("never more", widen.json()["detail"])

                empty = client.patch(path, json={"allowed_values": []})
                self.assertEqual(empty.status_code, 400)
                self.assertIn("fail every order", empty.json()["detail"])

                # a rule that checks no list has nothing to narrow
                wrong = client.patch("/api/partners/vsys/validation-rules/ssn",
                                     json={"allowed_values": ["anything"]})
                self.assertEqual(wrong.status_code, 400)

                # the narrowing survived every refusal
                self.assertEqual(binds.for_ats("vsys")["fcra"]["allowed_values"], ["Volunteer"])

    def test_unknown_exception_id_returns_404(self):
        from api import app

        client = TestClient(app)
        response = client.post("/api/exceptions/does-not-exist/close")
        self.assertEqual(response.status_code, 404)

    def test_bedrock_proposer_forces_tool_and_sends_paths_only(self):
        class FakeBedrock:
            def __init__(self):
                self.request = None

            def converse(self, **kwargs):
                self.request = kwargs
                return {
                    "usage": {"inputTokens": 100, "outputTokens": 40},
                    "output": {"message": {"content": [{"toolUse": {"input": {"proposals": [
                        {"destination": "given", "source": "person.first", "reason": "matching name"},
                        {"destination": "ssn", "source": "MISSING", "reason": "not present"},
                    ]}}}]}},
                }

        fake = FakeBedrock()
        proposer = BedrockProposer(model_id="us.example.model", client=fake)
        proposals = proposer({"person": {"first": "Ada", "ssn": "do-not-send"}}, ["given", "ssn"])
        message = fake.request["messages"][0]["content"][0]["text"]
        self.assertIn("person.first", message)
        self.assertNotIn("do-not-send", message)
        self.assertEqual(fake.request["toolConfig"]["toolChoice"]["tool"]["name"], "propose_mapping")
        self.assertEqual(proposer.last_usage["outputTokens"], 40)
        self.assertEqual(proposals[1]["source"], "MISSING")

    def test_describe_paths_marks_repeated_fields(self):
        paths = describe_paths({"addresses": [{"city": "London"}]})
        self.assertIn("addresses (repeats)", paths)
        self.assertIn("addresses.city", paths)

    def test_store_reloads_when_the_file_changes_underneath_it(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mappings.json"
            store = MappingStore(path)
            store.add_draft("ats", "candidate", [FieldMapping("a", "b")], proposed_by="author")
            self.assertEqual(len(store.list_partners()), 1)
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(store.list_partners(), [])

    def test_drift_counts_survive_a_process_but_not_a_reset(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "drift.json"
            issue = [{"field": "first", "message": "missing"}]
            tracker = DriftTracker(threshold=3, path=path)
            self.assertEqual(tracker.record("ats", "candidate", issue), [])
            self.assertEqual(tracker.record("ats", "candidate", issue), [])
            reopened = DriftTracker(threshold=3, path=path)
            self.assertEqual(len(reopened.record("ats", "candidate", issue)), 1)
            path.unlink()
            fresh = DriftTracker(threshold=3, path=path)
            self.assertEqual(fresh.record("ats", "candidate", issue), [])

    def test_replay_reports_when_there_is_nothing_to_check(self):
        from api import app

        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "mappings.json")
            store.add_draft("brand-new", "candidate", [FieldMapping("a", "b")], proposed_by="bedrock")
            with patch("api.store", store):
                result = TestClient(app).get("/api/mappings/brand-new/candidate/1/replay").json()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["results"], [])

    def test_format_rules_catch_a_bad_email(self):
        rule = ValidationRule("email_format", "Applicant.Email", "Format", "an email address", pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+")
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "m.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.Email", "Applicant.Email", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"Person": {"Email": "not-an-email"}}, [rule])
        self.assertEqual(result.status, "exception")
        self.assertIn("Applicant.Email", [issue["field"] for issue in result.issues])

    def test_business_check_rejects_an_under_age_applicant(self):
        from pipeline import check_min_age_18
        self.assertIsNone(check_min_age_18("1975-09-15"))
        self.assertIn("under the minimum age", check_min_age_18("2020-01-01") or "")

    def test_placeholder_ssns_are_rejected(self):
        from pipeline import check_ssn_not_placeholder
        self.assertIsNone(check_ssn_not_placeholder("530974151"))
        self.assertIsNotNone(check_ssn_not_placeholder("111111111"))
        self.assertIsNotNone(check_ssn_not_placeholder("000123456"))

    def catalogue(self, folder):
        rules = ValidationRuleStore(Path(folder) / "rules.json")
        rules.replace_all([
            ValidationRule("email_format", "Applicant.Email", "Format", "an email", pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+"),
            ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "an SSN", required=True),
        ])
        return rules

    def test_one_rule_serves_every_partner(self):
        """The catalogue is shared. Which partners are held to a rule is a
        binding, so a rule is written once rather than once per partner."""
        with TemporaryDirectory() as folder:
            rules = self.catalogue(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            for ats in ("vsys", "ideal-ats"):
                ids = {rule.id for rule in binds.rules_for(ats, rules.all())}
                self.assertEqual(ids, {"email_format", "ssn_present"})

    def test_presence_is_off_until_a_partner_is_bound_to_it(self):
        """A new partner gets shape checks but no presence demands, because
        what a partner actually sends is learned at onboarding."""
        with TemporaryDirectory() as folder:
            rules = self.catalogue(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            fresh = {rule.id: rule for rule in binds.rules_for("brand-new", rules.all())}
            self.assertTrue(fresh["email_format"].enabled)
            self.assertFalse(fresh["ssn_present"].required)

            binds.set("vsys", "ssn_present", required=True)
            vsys = {rule.id: rule for rule in binds.rules_for("vsys", rules.all())}
            ideal = {rule.id: rule for rule in binds.rules_for("ideal-ats", rules.all())}
            self.assertTrue(vsys["ssn_present"].required)
            self.assertFalse(ideal["ssn_present"].required)

    def test_binding_one_partner_leaves_the_others_alone(self):
        """Turning a rule off used to turn it off for everybody - the defect
        this split exists to fix."""
        with TemporaryDirectory() as folder:
            rules = self.catalogue(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "email_format", enabled=False)
            vsys = {rule.id: rule for rule in binds.rules_for("vsys", rules.all())}
            ideal = {rule.id: rule for rule in binds.rules_for("ideal-ats", rules.all())}
            self.assertFalse(vsys["email_format"].enabled)
            self.assertTrue(ideal["email_format"].enabled)
            # and the catalogue itself is untouched
            self.assertTrue(next(r for r in rules.all() if r.id == "email_format").enabled)

    def test_a_group_moves_together_and_leaves_other_groups_alone(self):
        """Select-all is one write. Twenty separate ones could half-finish and
        leave a group in a state nobody chose."""
        with TemporaryDirectory() as folder:
            rules = self.catalogue(folder)
            touched = rules.update_group("Completeness", required=False)
            self.assertEqual([rule.id for rule in touched], ["ssn_present"])
            after = {rule.id: rule for rule in rules.all()}
            self.assertFalse(after["ssn_present"].required)
            self.assertTrue(after["email_format"].enabled)

            # and it survives a reload, so the single write really happened
            self.assertFalse(
                next(r for r in ValidationRuleStore(Path(folder) / "rules.json").all()
                     if r.id == "ssn_present").required
            )

    def test_binding_a_group_binds_only_that_partner(self):
        with TemporaryDirectory() as folder:
            rules = self.catalogue(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            ids = [rule.id for rule in rules.all() if rule.group == "Completeness"]
            binds.set_group("vsys", ids, required=True, enabled=True)
            vsys = {rule.id: rule for rule in binds.rules_for("vsys", rules.all())}
            ideal = {rule.id: rule for rule in binds.rules_for("ideal-ats", rules.all())}
            self.assertTrue(vsys["ssn_present"].required)
            self.assertTrue(vsys["ssn_present"].bound)
            self.assertFalse(ideal["ssn_present"].required)

    def purposes(self, folder):
        rules = ValidationRuleStore(Path(folder) / "rules.json")
        rules.replace_all([
            ValidationRule("fcra", "FCRAPermissibleType", "Format", "a purpose",
                           allowed_values=("Volunteer", "Tenant Screening", "Employment Screening")),
            ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "an SSN", required=True),
        ])
        return rules

    def test_a_partner_can_be_held_to_fewer_values(self):
        """A client who screens volunteers should be held to Volunteer alone,
        not to every purpose the model accepts."""
        with TemporaryDirectory() as folder:
            rules = self.purposes(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "fcra", allowed_values=["Volunteer"])
            vsys = {r.id: r for r in binds.rules_for("vsys", rules.all())}
            other = {r.id: r for r in binds.rules_for("ideal-ats", rules.all())}
            self.assertEqual(vsys["fcra"].allowed_values, ("Volunteer",))
            # every other partner keeps the whole list
            self.assertEqual(len(other["fcra"].allowed_values), 3)
            # and the catalogue itself is untouched
            self.assertEqual(len(next(r for r in rules.all() if r.id == "fcra").allowed_values), 3)

    def test_a_narrowed_rule_rejects_what_it_no_longer_allows(self):
        with TemporaryDirectory() as folder:
            rules = self.purposes(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "fcra", allowed_values=["Volunteer"])
            store = MappingStore(Path(folder) / "m.json")
            store.add_draft("vsys", "background",
                            [FieldMapping("purpose", "FCRAPermissibleType")], proposed_by="author")
            store.approve("vsys", "background", 1, "reviewer")
            pipe = Pipeline(store)

            good = pipe.process("vsys", "background", {"purpose": "Volunteer"},
                                binds.rules_for("vsys", rules.all()))
            self.assertEqual(good.status, "processed")
            # accepted for anyone else, refused for this partner
            bad = pipe.process("vsys", "background", {"purpose": "Tenant Screening"},
                               binds.rules_for("vsys", rules.all()))
            self.assertEqual(bad.status, "exception")

    def test_a_binding_cannot_widen_what_the_model_accepts(self):
        """Narrowing is a partner's business; widening is the catalogue's. A
        stored value the catalogue never listed is dropped, not honoured."""
        with TemporaryDirectory() as folder:
            rules = self.purposes(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "fcra", allowed_values=["Volunteer", "Anything At All"])
            applied = {r.id: r for r in binds.rules_for("vsys", rules.all())}
            self.assertEqual(applied["fcra"].allowed_values, ("Volunteer",))

    def test_a_narrowing_that_permits_nothing_is_ignored(self):
        """A rule allowing no value would fail every order, which is never
        what someone meant."""
        with TemporaryDirectory() as folder:
            rules = self.purposes(folder)
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "fcra", allowed_values=["Nothing Valid"])
            applied = {r.id: r for r in binds.rules_for("vsys", rules.all())}
            self.assertEqual(len(applied["fcra"].allowed_values), 3)

    def test_covering_every_value_lifts_the_narrowing(self):
        with TemporaryDirectory() as folder:
            binds = RuleBindingStore(Path(folder) / "bindings.json")
            binds.set("vsys", "fcra", allowed_values=["Volunteer"])
            self.assertIn("allowed_values", binds.for_ats("vsys")["fcra"])
            binds.set("vsys", "fcra", allowed_values=[])   # what the API sends back
            self.assertNotIn("allowed_values", binds.for_ats("vsys")["fcra"])

    def test_a_disabled_rule_does_nothing(self):
        rule = ValidationRule("email_format", "Applicant.Email", "Format", "an email", pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", enabled=False)
        with TemporaryDirectory() as folder:
            store = MappingStore(Path(folder) / "m.json")
            store.add_draft("ats", "candidate", [FieldMapping("Person.Email", "Applicant.Email", True)], proposed_by="author")
            store.approve("ats", "candidate", 1, "reviewer")
            result = Pipeline(store).process("ats", "candidate", {"Person": {"Email": "not-an-email"}}, [rule])
        self.assertEqual(result.status, "processed")


if __name__ == "__main__":
    unittest.main()