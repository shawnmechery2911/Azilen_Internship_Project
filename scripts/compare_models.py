"""Compare Bedrock models as the mapping proposer.

The proposer runs at design time only - a handful of calls per partner, ever -
so a cheaper model saves very little. What it can cost is abstention
discipline, and that is what this measures: not just how many fields a model
maps, but whether it invents a mapping for a destination the payload has no
source for. A field quietly filled with the wrong value is worse than one left
unmapped, because the replay guardrail only catches source paths that do not
exist.

    python scripts/compare_models.py
    python scripts/compare_models.py --models us.anthropic.claude-sonnet-5 qwen.qwen3-32b-v1:0
    python scripts/compare_models.py --trials 5

List what an account can reach with:
    aws bedrock list-foundation-models --region us-east-2
    aws bedrock list-inference-profiles --region us-east-2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pipeline  # noqa: E402
from bedrock_proposer import BedrockProposer, describe_paths  # noqa: E402

DEFAULT_MODELS = ["us.anthropic.claude-sonnet-5", "qwen.qwen3-32b-v1:0"]

# A partner nobody has seen before, deliberately not one of the fixtures: it
# holds eight fields that map cleanly and, importantly, no phone number.
PAYLOAD = """<Order>
  <Account>ACME-77</Account>
  <Candidate>
    <Given>Grace</Given><Sur>Hopper</Sur>
    <Mail>grace@acme.test</Mail><Born>12/09/1986</Born>
    <Ssn>412558891</Ssn>
    <Home><Town>Arlington</Town><Region>VA</Region><Post>22201</Post></Home>
  </Candidate>
  <Package>Standard</Package>
</Order>"""

# The answer, for the destinations this payload can actually fill.
EXPECTED = {
    "AccountNumber": "Account",
    "Applicant.Names[0].GivenName": "Candidate.Given",
    "Applicant.Names[0].FamilyName": "Candidate.Sur",
    "Applicant.Email": "Candidate.Mail",
    "Applicant.SSN": "Candidate.Ssn",
    "Applicant.DateOfBirth": "Candidate.Born",
    "Request.BackgroundOrder.BackgroundPackageName": "Package",
    "Applicant.Addresses.City": "Candidate.Home.Town",
}

# Destinations this payload has no source for. Mapping any of these is the
# failure that matters - the model filled a field it should have declined.
SHOULD_ABSTAIN = {
    "Applicant.PhoneNumber",
    "Applicant.Names[0].MiddleName",
    "Applicant.Names[0].Suffix",
    "TransactInfo.TransactId",
}


def destinations() -> list[str]:
    raw = json.loads((ROOT / "fixtures" / "destination-fields.json").read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else list(raw.values())[0]


def run(model: str, trials: int) -> None:
    payload = pipeline.parse_input(PAYLOAD)
    targets = destinations()
    real_paths = set(describe_paths(payload))

    shapes: list[frozenset[tuple[str, str]]] = []
    invented: list[tuple[str, str]] = []
    wrongly_filled: list[tuple[str, str]] = []
    correct = 0
    tokens = 0
    seconds = 0.0

    for trial in range(trials):
        adapter = pipeline.LLMMappingDraft(BedrockProposer(model_id=model))
        started = time.time()
        try:
            mappings = adapter.draft(payload, targets)
        except Exception as error:  # a model that cannot be used is a result
            print(f"   trial {trial + 1}: FAILED {type(error).__name__}: {str(error)[:120]}")
            continue
        seconds += time.time() - started
        usage = getattr(adapter.proposer, "last_usage", None) or {}
        tokens += (usage.get("inputTokens") or 0) + (usage.get("outputTokens") or 0)

        got = {m.destination: m.source for m in mappings}
        shapes.append(frozenset(got.items()))
        correct += sum(1 for dest, src in EXPECTED.items() if got.get(dest) == src)
        for dest, src in got.items():
            if not src.startswith("Static:") and src not in real_paths:
                invented.append((dest, src))
            if dest in SHOULD_ABSTAIN:
                wrongly_filled.append((dest, src))
        print(
            f"   trial {trial + 1}: {len(mappings)} mapped,"
            f" {len(getattr(adapter, 'abstentions', []))} abstained"
        )

    if not shapes:
        return
    runs = len(shapes)
    print(f"   correct        {correct / runs:.1f} of {len(EXPECTED)} per run")
    print(f"   deterministic  {'yes' if all(s == shapes[0] for s in shapes) else 'NO - output differed between runs'}")
    print(f"   invented paths {invented or 'none'}")
    print(f"   filled a field it had no source for: {wrongly_filled or 'none'}")
    print(f"   {tokens // runs} tokens/run, {seconds / runs:.1f}s/run")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()

    for model in args.models:
        print("=" * 66)
        print(model)
        run(model, args.trials)


if __name__ == "__main__":
    main()
