"""AWS Bedrock-backed mapping proposer.

This module is only used during mapping draft or repair workflows. Runtime
payload processing remains deterministic and never calls Bedrock.
"""

from __future__ import annotations

import os
from typing import Any

import boto3
from dotenv import load_dotenv

from pipeline import LLMMappingDraft, MappingDraft

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-2")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
TRANSFORMS = ["identity", "trim", "digits_only", "phone", "date"]

SYSTEM_PROMPT = """You design field mappings for a background-check system.

You are given the field paths available in a partner payload and the destination
fields our system needs. Return one proposal for every destination field.

Rules:
1. Only use source paths from the supplied list. Never invent a path.
2. If a destination has no matching source, set source to exactly MISSING and
   explain why in reason. This is a correct answer, not a failure.
3. Match on meaning, not spelling. FirstName and GivenName are equivalent;
   Package and BackgroundPackageName are equivalent.
4. Set source_is_list to true when the source path can repeat.
5. Use only these transforms: identity, trim, digits_only, phone, date.
   Use identity when no cleanup is needed or you are unsure.
6. Give a short reason for every field, mapped or abstained.

Do not skip destination fields and do not include values from the payload.
"""

MAPPING_TOOL = {
    "toolSpec": {
        "name": "propose_mapping",
        "description": "Propose a source field for every destination field.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "proposals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "destination": {"type": "string"},
                                "source": {"type": "string"},
                                "required": {"type": "boolean"},
                                "transform": {"type": "string", "enum": TRANSFORMS},
                                "source_is_list": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["destination", "source", "reason"],
                        },
                    }
                },
                "required": ["proposals"],
            }
        },
    }
}


def describe_paths(value: Any, prefix: str = "") -> list[str]:
    """List payload field paths without sending payload values to the model."""
    paths: list[str] = []
    if not isinstance(value, dict):
        return paths
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            paths.extend(describe_paths(child, path))
        elif isinstance(child, list):
            paths.append(f"{path} (repeats)")
            if child and isinstance(child[0], dict):
                paths.extend(describe_paths(child[0], path))
        else:
            paths.append(path)
    return paths


class BedrockProposer:
    """Callable adapter consumed by ``LLMMappingDraft``."""

    def __init__(self, model_id: str = "", region: str = REGION, client: Any = None) -> None:
        self.model_id = model_id or MODEL_ID
        if not self.model_id:
            raise ValueError("Set BEDROCK_MODEL_ID or pass model_id")
        self.client = client or boto3.client("bedrock-runtime", region_name=region)
        self.last_usage: dict[str, Any] | None = None

    def __call__(self, payload: dict[str, Any], destination_fields: list[str]) -> list[dict[str, Any]]:
        source_paths = describe_paths(payload)
        user_message = (
            "Source paths available in this payload:\n"
            + "\n".join(f"  {path}" for path in source_paths)
            + "\n\nDestination fields to fill:\n"
            + "\n".join(f"  {field}" for field in destination_fields)
            + "\n\nPropose one entry for every destination field."
        )
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 4096},
            toolConfig={"tools": [MAPPING_TOOL], "toolChoice": {"tool": {"name": "propose_mapping"}}},
        )
        self.last_usage = response.get("usage")
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block:
                return block["toolUse"]["input"]["proposals"]
        raise RuntimeError("The model did not return a mapping proposal")


def make_adapter() -> MappingDraft | LLMMappingDraft:
    """Use Bedrock only when configured; preserve an offline path for tests."""
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK") and os.getenv("BEDROCK_MODEL_ID"):
        print(f"Using Bedrock: {os.getenv('BEDROCK_MODEL_ID')}")
        return LLMMappingDraft(BedrockProposer())
    print("Bedrock not configured - using offline name matcher")
    return MappingDraft()


if __name__ == "__main__":
    print("Bedrock proposer module ready.")
    print(f"Region: {REGION}")
    print("Configured:", bool(os.getenv("AWS_BEARER_TOKEN_BEDROCK") and os.getenv("BEDROCK_MODEL_ID")))
