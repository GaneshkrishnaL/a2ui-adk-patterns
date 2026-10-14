# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# A2UI v0.9 Catalog, Validator, Auto-Healing Parser & A2A PartConverter
# (100% Generic Reference Implementation for ADK + A2A)

from __future__ import annotations

import copy
import json
import re
from typing import Any

from a2a import types as a2a_types
from google.adk.a2a import _compat as a2a_compat
from google.adk.a2a.converters import part_converter as adk_part_converter
from google.genai import types as genai_types
import jsonschema

A2UI_MIME_TYPE = "application/a2ui+json"
A2UI_VERSION = "v0.9"
A2UI_OPEN_TAG = "<a2ui-json>"
A2UI_CLOSE_TAG = "</a2ui-json>"
A2UI_TOOL_NAME = "send_a2ui_json_to_client"
A2UI_VALIDATED_KEY = "validated_a2ui_json"
A2UI_ERROR_KEY = "a2ui_validation_error"

CARE_PORTAL_CATALOG_ID = (
    "https://example.org/a2ui_catalogs/care_portal_v1.json"
)

# ============================================================================
# 1. Generic Care Portal Component Catalog & Envelope JSON Schema (A2UI v0.9)
# ============================================================================

CARE_PORTAL_A2UI_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "A2UI v0.9 Envelope Message List",
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["version"],
        "properties": {
            "version": {"type": "string", "enum": ["v0.9", "v0.9.1"]},
            "createSurface": {
                "type": "object",
                "required": ["surfaceId", "catalogId"],
                "properties": {
                    "surfaceId": {"type": "string", "minLength": 1},
                    "catalogId": {"type": "string", "minLength": 1},
                    "theme": {"type": "object"},
                    "sendDataModel": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            "updateComponents": {
                "type": "object",
                "required": ["surfaceId", "components"],
                "properties": {
                    "surfaceId": {"type": "string", "minLength": 1},
                    "components": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["id", "component"],
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "component": {
                                    "type": "string",
                                    "enum": [
                                        # Standard A2UI v0.9 primitives
                                        "Card",
                                        "Column",
                                        "Row",
                                        "List",
                                        "Text",
                                        "Button",
                                        "TextField",
                                        "ChoicePicker",
                                        "DateTimeInput",
                                        "CheckBox",
                                        "Divider",
                                        # Bespoke Domain Catalog Components
                                        "AppointmentSlotPickerCard",
                                        "TriageIntakeCard",
                                        "CopaySummaryBadge",
                                    ],
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                },
                "additionalProperties": False,
            },
            "updateDataModel": {
                "type": "object",
                "required": ["surfaceId", "path"],
                "properties": {
                    "surfaceId": {"type": "string", "minLength": 1},
                    "path": {"type": "string", "pattern": "^/.*"},
                    "value": {},
                },
                "additionalProperties": False,
            },
            "deleteSurface": {
                "type": "object",
                "required": ["surfaceId"],
                "properties": {
                    "surfaceId": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
        "oneOf": [
            {"required": ["createSurface"]},
            {"required": ["updateComponents"]},
            {"required": ["updateDataModel"]},
            {"required": ["deleteSurface"]},
        ],
    },
}


def generate_a2ui_system_prompt(
    role_description: str,
    ui_description: str,
    catalog_id: str = CARE_PORTAL_CATALOG_ID,
) -> str:
  """Generates system prompt instructions with A2UI v0.9 schema rules and examples.

  Mirrors `A2uiSchemaManager.generate_system_prompt(...)` in `a2ui-agent-sdk`.
  """
  return (
      f"{role_description}\n\n"
      f"### A2UI (Agent-to-UI) v0.9 Generation Instructions\n"
      f"{ui_description}\n"
      f"- Active Catalog ID: `{catalog_id}`\n"
      f"- Wrap all A2UI JSON arrays inside `{A2UI_OPEN_TAG}...{A2UI_CLOSE_TAG}` tags.\n"
      f"- Every message in the array MUST include `\"version\": \"v0.9\"` and one of:\n"
      f"  `createSurface`, `updateComponents`, `updateDataModel`, or `deleteSurface`.\n"
      f"- In `updateComponents`, use a flat adjacency list of components where at least\n"
      f"  one component has `\"id\": \"root\"`.\n"
      f"- Bind dynamic properties to JSON Pointers (e.g., `{{\"path\": \"/patient/urgency\"}}`).\n"
  )


def parse_and_fix_a2ui_json(raw_json_str: str) -> list[dict[str, Any]]:
  """Auto-heals common LLM JSON formatting quirks and validates against A2UI v0.9 schema.

  Mirrors `DirectJsonParser.parse_and_fix(...)` and `A2uiValidator.validate(...)`:
    1. Strips markdown code fences (```json ... ```) or `<a2ui-json>` tags.
    2. Repairs trailing commas before `]` or `}`.
    3. Wraps a single envelope dict in a list `[...]` if needed.
    4. Validates against `CARE_PORTAL_A2UI_SCHEMA` AND verifies that any initial
       `updateComponents` message includes a root component (`"id": "root"`).
  """
  cleaned = raw_json_str.strip()
  cleaned = re.sub(r"^<a2ui-json>\s*", "", cleaned)
  cleaned = re.sub(r"\s*</a2ui-json>$", "", cleaned)
  cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
  cleaned = re.sub(r"\s*```$", "", cleaned)
  # Auto-heal trailing commas before closing brackets/braces
  cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

  parsed = json.loads(cleaned)
  if isinstance(parsed, dict):
    parsed = [parsed]
  if not isinstance(parsed, list):
    raise ValueError("A2UI payload must be a JSON array of envelope objects.")

  jsonschema.validate(instance=parsed, schema=CARE_PORTAL_A2UI_SCHEMA)

  # Semantic check: every `updateComponents` block that initializes a surface
  # must contain a component with `"id": "root"`.
  for idx, msg in enumerate(parsed):
    if "updateComponents" in msg:
      components = msg["updateComponents"].get("components", [])
      ids = {c.get("id") for c in components if isinstance(c, dict)}
      if "root" not in ids:
        raise ValueError(
            f"Envelope message [{idx}] `updateComponents` for surface"
            f" '{msg['updateComponents'].get('surfaceId')}' is missing a root"
            f" component (`\"id\": \"root\"`). Found component IDs: {sorted(ids)}"
        )

  return parsed


def create_a2ui_datapart(envelope_msg: dict[str, Any]) -> a2a_types.Part:
  """Wraps a single validated A2UI v0.9 envelope dict into an A2A `DataPart`."""
  return a2a_compat.make_data_part(
      data=copy.deepcopy(envelope_msg),
      metadata={"mimeType": A2UI_MIME_TYPE},
  )


def extract_text_and_a2ui_parts(
    raw_text: str,
    fallback_text: str | None = None,
) -> list[a2a_types.Part]:
  """Splits text containing `<a2ui-json>...</a2ui-json>` into A2A `TextPart` + `DataPart`s."""
  pattern = re.compile(
      rf"{re.escape(A2UI_OPEN_TAG)}(.*?){re.escape(A2UI_CLOSE_TAG)}",
      re.DOTALL,
  )
  parts: list[a2a_types.Part] = []
  last_end = 0

  for match in pattern.finditer(raw_text):
    prefix_text = raw_text[last_end : match.start()].strip()
    if prefix_text:
      parts.append(a2a_compat.make_text_part(prefix_text))

    json_block = match.group(1)
    try:
      envelopes = parse_and_fix_a2ui_json(json_block)
      for env in envelopes:
        parts.append(create_a2ui_datapart(env))
    except Exception as exc:  # pylint: disable=broad-except
      if fallback_text:
        parts.append(a2a_compat.make_text_part(f"{fallback_text} ({exc})"))
    last_end = match.end()

  trailing_text = raw_text[last_end:].strip()
  if trailing_text:
    parts.append(a2a_compat.make_text_part(trailing_text))

  return parts


class A2uiPartConverter:
  """Catalog-aware GenAI-to-A2A part converter supporting all A2UI patterns.

  Handles:
    1. Pattern 3 (`SendA2uiToClientToolset` -> `send_a2ui_json_to_client` tool response)
    2. Pattern 2 (Deterministic tool response containing `<a2ui-json>...</a2ui-json>`)
    3. Pattern 1 & Pattern 4 (LLM text or `before_model_callback` containing `<a2ui-json>`)
  """

  def __init__(self, fallback_text: str | None = None) -> None:
    self._fallback_text = fallback_text

  def convert(self, part: genai_types.Part) -> list[a2a_types.Part]:
    # 1. Tool Responses (`FunctionResponse`)
    if fn_resp := part.function_response:
      response_dict = fn_resp.response or {}
      if fn_resp.name == A2UI_TOOL_NAME:
        if A2UI_ERROR_KEY in response_dict:
          return []
        if A2UI_VALIDATED_KEY in response_dict:
          envelopes = response_dict[A2UI_VALIDATED_KEY] or []
          return [create_a2ui_datapart(env) for env in envelopes]
        return []

      result_str = response_dict.get("result")
      if isinstance(result_str, str) and A2UI_OPEN_TAG in result_str:
        return extract_text_and_a2ui_parts(
            result_str, fallback_text=self._fallback_text
        )

    # 2. Suppress internal `send_a2ui_json_to_client` FunctionCall parts from wire
    if (fn_call := part.function_call) and fn_call.name == A2UI_TOOL_NAME:
      return []

    # 3. Text-based A2UI (`<a2ui-json>...</a2ui-json>`)
    if part.text and A2UI_OPEN_TAG in part.text:
      return extract_text_and_a2ui_parts(
          part.text, fallback_text=self._fallback_text
      )

    # 4. Default conversion for normal parts
    converted = adk_part_converter.convert_genai_part_to_a2a_part(part)
    if isinstance(converted, list):
      return converted
    return [converted] if converted else []
