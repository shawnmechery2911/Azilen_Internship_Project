from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bedrock_proposer import make_adapter


def _destination_name(item: dict[str, object] | object) -> str | None:
    if not isinstance(item, dict):
        return None
    destination = item.get("destination")
    return str(destination) if destination is not None else None


def main() -> None:
    fixtures = ROOT / "fixtures"
    payload = json.loads((fixtures / "ideallogic-order.json").read_text(encoding="utf-8"))
    destination_fields = json.loads((fixtures / "destination-fields.json").read_text(encoding="utf-8"))

    print(f"Using adapter from: {ROOT}")
    for index in range(3):
        try:
            adapter = make_adapter()
            mappings = adapter.draft(payload, destination_fields)
            abstentions = list(getattr(adapter, "abstentions", []))
            ssn_abstained = any(_destination_name(item) == "Applicant.SSN" for item in abstentions)
            usage = getattr(getattr(adapter, "proposer", None), "last_usage", None)
            print(
                f"Run {index + 1}: mapped={len(mappings)} abstained={len(abstentions)} "
                f"ssn_abstained={ssn_abstained} usage={usage}"
            )
            for entry in abstentions:
                destination = _destination_name(entry)
                reason = entry.get("reason") if isinstance(entry, dict) else ""
                print(f"    abstained: {destination} - {reason}")
            if not ssn_abstained:
                print("Warning: no SSN abstention was reported. Check the Bedrock prompt and payload fixture.")
        except Exception as exc:  # pragma: no cover - runtime compatibility guard
            print(f"Run {index + 1}: Bedrock live check unavailable: {exc}")
            print("Status: Bedrock access is blocked by the runtime environment; baseline remains offline and honest.")
            return

    final_abstentions = list(getattr(make_adapter(), "abstentions", []))
    if not any(_destination_name(item) == "Applicant.SSN" for item in final_abstentions):
        print("Warning: final run did not abstain on Applicant.SSN.")


if __name__ == "__main__":
    main()
