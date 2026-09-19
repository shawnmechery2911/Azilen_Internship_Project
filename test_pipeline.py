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
    Pipeline,
    RuleBindingStore,
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

    def test_drift_requires_repeated_failures(self):
        with TemporaryDirectory() as folder:
            tracker = DriftTracker(threshold=2, path=Path(folder) / "drift.json")
            issue = [{"field": "first", "message": "missing"}]
            self.assertEqual(tracker.record("ats", "candidate", issue), [])
            self.assertEqual(len(tracker.record("ats", "candidate", issue)), 1)

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
            rule = ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "an SSN", required=True)

            demanded = pipeline.process("ats", "candidate", {"Person": {}}, [rule])
            self.assertEqual(demanded.status, "exception")
            self.assertEqual([i["field"] for i in demanded.issues], ["Applicant.SSN"])

            relaxed = pipeline.process("ats", "candidate", {"Person": {}}, [replace(rule, required=False)])
            self.assertEqual(relaxed.status, "processed")
            self.assertEqual(relaxed.issues, [])

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
        self.assertTrue(any("TransactInfo.TransactId" in issue["field"] for issue in result.issues))

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
                 patch("api.make_adapter", return_value=adapter):
                client = TestClient(api.app)
                response = client.post(
                    "/api/mappings/demo-ats/candidate/draft",
                    json={"payload": {"person": {"first": "Ada"}}, "destination_fields": ["given", "ssn"]},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["abstentions"][0]["destination"], "ssn")

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