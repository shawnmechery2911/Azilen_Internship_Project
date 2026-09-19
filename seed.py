"""Create the deterministic four-beat demo dataset."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import ExceptionQueue, FieldMapping, MappingStore, Pipeline, ProcessingLog, ValidationRule, ValidationRuleStore

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

DEFAULT_RULES = [
    ValidationRule("sender_present", "Sender.Id", "Completeness", "the sending system id", required=True),
    ValidationRule("account_present", "AccountNumber", "Completeness", "the billing account", required=True),
    ValidationRule("package_present", "Request.BackgroundOrder.BackgroundPackageName", "Completeness", "the ordered screening package", required=True),
    ValidationRule("given_name_present", "Applicant.Names[0].GivenName", "Completeness", "the applicant's first name", required=True),
    ValidationRule("family_name_present", "Applicant.Names[0].FamilyName", "Completeness", "the applicant's surname", required=True),
    ValidationRule("email_present", "Applicant.Email", "Completeness", "an email to send the invitation to", required=True),
    ValidationRule("applicant_id_present", "Applicant.ApplicantId", "Completeness", "the partner's own id for this applicant", required=True),
    ValidationRule("email_format", "Applicant.Email", "Format", "an email address", pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+"),
    ValidationRule("ssn_format", "Applicant.SSN", "Format", "nine digits", pattern=r"\d{9}"),
    ValidationRule("phone_format", "Applicant.PhoneNumber", "Format", "10 to 15 digits", pattern=r"\+?\d{10,15}"),
    ValidationRule("dob_iso", "Applicant.DateOfBirth", "Format", "an ISO date", pattern=r"\d{4}-\d{2}-\d{2}"),
    ValidationRule("account_digits", "AccountNumber", "Format", "4 to 10 digits", pattern=r"\d{4,10}"),
    ValidationRule("version_format", "Version", "Format", "a version like 1.0", pattern=r"\d+\.\d+"),
    ValidationRule("name_type_enum", "Applicant.Names[0].Type", "Format", "a known name type", allowed_values=("MAIN", "AKA", "MAIDEN")),
    ValidationRule("samba_flag", "Request.BackgroundOrder.AddToSamba", "Format", "a boolean flag", allowed_values=("true", "false")),
    ValidationRule("fcra_purpose", "FCRAPermissibleType", "Format", "a permissible FCRA purpose", allowed_values=("Preemployment Screening", "Volunteer", "Employment Screening", "Tenant Screening")),
    ValidationRule("dob_min_age_18", "Applicant.DateOfBirth", "Business", "an applicant aged 18 or over", check="min_age_18"),
    ValidationRule("ssn_not_placeholder", "Applicant.SSN", "Business", "an SSN that could be real", check="ssn_not_placeholder"),
    # These were four near-duplicate rules carrying ats="vsys". They are ordinary
    # catalogue rules now; whether a partner is held to them is a binding.
    ValidationRule("ssn_present", "Applicant.SSN", "Completeness", "a social security number", required=True),
    ValidationRule("dob_present", "Applicant.DateOfBirth", "Completeness", "a date of birth", required=True),
    ValidationRule("phone_present", "Applicant.PhoneNumber", "Completeness", "a phone number", required=True),
    ValidationRule("city_present", "Applicant.Addresses.City", "Completeness", "an address history", required=True),
    # Every remaining destination field, so all 18 appear on the Validation
    # screen and presence can be demanded per partner with a toggle. They ship
    # not-required because no current partner sends them - switching one on
    # without the partner sending it would fail every order for that partner.
    ValidationRule("method_name_present", "MethodName", "Completeness", "the request method name"),
    ValidationRule("transact_id_present", "TransactInfo.TransactId", "Completeness", "the partner's transaction id"),
    ValidationRule("partner_ref_present", "Applicant.PartnerReference1", "Completeness", "the partner's own reference"),
    ValidationRule("middle_name_present", "Applicant.Names[0].MiddleName", "Completeness", "the applicant's middle name"),
    ValidationRule("suffix_present", "Applicant.Names[0].Suffix", "Completeness", "the applicant's name suffix"),
]


def read_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def seed() -> None:
    store_path = ROOT / "mapping_store.json"
    exceptions_path = ROOT / "exceptions.json"
    activity_path = ROOT / "processing_log.json"
    rules_path = ROOT / "validation_rules.json"
    # Rules are topped up even on an already-seeded install: a new default rule
    # should reach an existing demo without wiping the toggles someone set.
    # Matching is by id, so an edited rule is left exactly as it is.
    rules = ValidationRuleStore(rules_path)
    known = {rule.id for rule in rules.all()}
    added = [rule for rule in DEFAULT_RULES if rule.id not in known]
    if added:
        rules.replace_all(rules.all() + added)
        print(f"added {len(added)} new validation rule(s): {', '.join(rule.id for rule in added)}")

    if store_path.exists() and exceptions_path.exists() and activity_path.exists():
        return

    store = MappingStore(store_path)
    ideal_rows = [
        # the fixture carries the approver's required flags; they were being
        # overwritten to False, which only worked while every absent field was
        # reported regardless
        FieldMapping(**row)
        for row in json.loads((FIXTURES / "ideallogic-mapping.json").read_text(encoding="utf-8"))
        if row["source"].startswith("Static:") or row["source"] in {
            "Username", "AccountNumber", "Package", "FCRAPurpose", "Person.ApplicantID",
            "Person.FirstName", "Person.LastName", "Person.Email",
        }
    ]
    store.add_draft("ideal-ats", "candidate", ideal_rows, proposed_by="seed")
    store.approve("ideal-ats", "candidate", 1, "reviewer", [read_json("ideallogic-order.json")])

    vsys_rows = [
        FieldMapping("Username", "Sender.Id", required=True),
        FieldMapping("AccountNumber", "AccountNumber", required=True),
        FieldMapping("Package", "Request.BackgroundOrder.BackgroundPackageName", required=True),
        FieldMapping("Person.FirstName", "Applicant.Names[0].GivenName", required=True),
        FieldMapping("Person.LastName", "Applicant.Names[0].FamilyName", required=True),
        FieldMapping("Person.Email", "Applicant.Email", required=True),
        FieldMapping("Person.ApplicantID", "Applicant.ApplicantId", required=True),
        FieldMapping("Person.SSN", "Applicant.SSN", required=True, transform="digits_only"),
        FieldMapping("Person.DOB", "Applicant.DateOfBirth", required=True, transform="date"),
        FieldMapping("Person.Phone", "Applicant.PhoneNumber", transform="phone"),
        FieldMapping("Person.AddressHistory.Address.City", "Applicant.Addresses.City", source_is_list=True),
    ]
    vsys_payloads = [read_xml("vsys-order.xml"), read_xml("vsys-order-2addresses.xml")]
    store.add_draft("vsys", "background", vsys_rows, proposed_by="seed")
    store.approve("vsys", "background", 1, "reviewer", vsys_payloads)

    store.add_draft("new-partner", "candidate", [FieldMapping("Person.FirstName", "Applicant.Names[0].GivenName")], proposed_by="bedrock", abstentions=[{"destination": "Applicant.SSN", "reason": "SSN is not present in the uploaded sample"}])

    tracker_pipeline = Pipeline(store)
    log = ProcessingLog(activity_path)
    ideal_payload = read_json("ideallogic-order.json")
    for payload in (ideal_payload, ideal_payload, {"Username": "broken"}):
        result = tracker_pipeline.process("ideal-ats", "candidate", payload)
        log.add("ideal-ats", "candidate", result)

    queue = ExceptionQueue(exceptions_path)
    bad_result = tracker_pipeline.process("ideal-ats", "candidate", {"Username": "broken"})
    queue.add("ideal-ats", "candidate", {"Username": "broken"}, bad_result)
    queue.add("vsys", "background", {"Username": "broken"}, tracker_pipeline.process("vsys", "background", {"Username": "broken"}))


def read_xml(name: str) -> dict:
    from pipeline import parse_input
    return parse_input((FIXTURES / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    seed()
