from pathlib import Path

from pipeline import FieldMapping, ExceptionQueue, MappingStore, Pipeline, ValidationRule


def main() -> None:
    data_dir = Path("demo-data")
    store = MappingStore(data_dir / "mapping_store.json")
    if store.get("demo-ats", "candidate") is None:
        store.add_draft(
            "demo-ats",
            "candidate",
            [
                FieldMapping("person.firstName", "candidate.given_name", required=True),
                FieldMapping("person.lastName", "candidate.family_name", required=True),
                FieldMapping("person.email", "candidate.email", required=True),
            ],
            proposed_by="demo",
        )
        store.approve("demo-ats", "candidate", 1, "demo-reviewer")

    payload = {"person": {"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.com"}}
    result = Pipeline(store).process(
        "demo-ats",
        "candidate",
        payload,
        [ValidationRule("email_format", "candidate.email", required=True, pattern=r"[^@]+@[^@]+")],
    )
    if result.status == "exception":
        ExceptionQueue(data_dir / "exceptions.json").add("demo-ats", "candidate", payload, result)
    print(result.status)
    print(result.mapped_payload)
    print(f"mapping_version={result.mapping_version}")


if __name__ == "__main__":
    main()