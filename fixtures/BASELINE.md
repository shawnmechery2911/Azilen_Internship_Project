# Bedrock baseline

This file records the latest model score against the IdealLogic fixture.

## Current status

The live Bedrock model is not currently usable from this workspace. The runtime is rejecting the configured model with an access error, so this remains an honest offline baseline rather than a production-model result.

## Offline baseline

- Model adapter: `MappingDraft`
- Reason: the runtime is configured with a Bedrock model ID, but the provider is rejecting access to that model in this environment
- Result: the offline matcher uses name-based fallback and cannot emit a real Bedrock abstention report
- SSN result: `Applicant.SSN` is not abstained in the offline path; the model is not live

## Expected live result

- `Applicant.SSN` must be abstained rather than invented.
- The model should beat the offline baseline of 3/8 real fields.
- A valid run must show more than three mapped fields and a reasoned abstention for `Applicant.SSN`.

## Run 1

- live Bedrock check: blocked by provider access error
- mapped fields: unavailable
- abstained fields: unavailable

## Run 2

- live Bedrock check: blocked by provider access error
- mapped fields: unavailable
- abstained fields: unavailable

## Run 3

- live Bedrock check: blocked by provider access error
- mapped fields: unavailable
- abstained fields: unavailable

## Next action

Fix the Bedrock model access in AWS/Bedrock and rerun `py scripts/score_model.py` to replace these placeholders with real live metrics.
