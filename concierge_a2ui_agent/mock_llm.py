# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Model Factory supporting Vertex AI (`gemini-2.5-flash`) by default or
# deterministic offline execution (`--offline-mock`) for all 5 A2UI patterns.

from __future__ import annotations

import json
import os
from typing import AsyncGenerator

from a2ui_orchestration_bridge import GLOBAL_TRACE_RECORDER
from catalog_and_schema import A2UI_CLOSE_TAG
from catalog_and_schema import A2UI_ERROR_KEY
from catalog_and_schema import A2UI_OPEN_TAG
from catalog_and_schema import CARE_PORTAL_CATALOG_ID
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def _usage(in_tok: int, out_tok: int) -> types.GenerateContentResponseUsageMetadata:
  return types.GenerateContentResponseUsageMetadata(
      prompt_token_count=in_tok,
      candidates_token_count=out_tok,
      total_token_count=in_tok + out_tok,
  )


def _extract_last_function_responses(
    contents: list[types.Content],
) -> list[types.FunctionResponse]:
  if not contents:
    return []
  last = contents[-1]
  if not last.parts:
    return []
  return [p.function_response for p in last.parts if p.function_response]


class OfflineDeterministicA2uiLlm(BaseLlm):
  """Deterministic ADK BaseLlm for executing all 5 A2UI patterns offline (`--offline-mock`)."""

  model: str = "offline-deterministic-a2ui-llm"
  role_name: str = "generic"

  async def generate_content_async(
      self, llm_request: LlmRequest, stream: bool = False
  ) -> AsyncGenerator[LlmResponse, None]:
    del stream
    fn_responses = _extract_last_function_responses(llm_request.contents)

    # 1. Pattern 1: Prompt-Driven Dynamic LLM UI Generation
    if self.role_name == "pattern1_dynamic_ui":
      dynamic_envelopes = [
          {
              "version": "v0.9",
              "createSurface": {
                  "surfaceId": "clinic_comparison_surface",
                  "catalogId": CARE_PORTAL_CATALOG_ID,
                  "theme": {
                      "primaryColor": "#028090",
                      "agentDisplayName": "Care Concierge",
                  },
              },
          },
          {
              "version": "v0.9",
              "updateComponents": {
                  "surfaceId": "clinic_comparison_surface",
                  "components": [
                      {
                          "id": "root",
                          "component": "Card",
                          "children": ["title_txt", "clinic_list"],
                      },
                      {
                          "id": "title_txt",
                          "component": "Text",
                          "text": {"path": "/comparisonTitle"},
                          "variant": "h3",
                      },
                      {
                          "id": "clinic_list",
                          "component": "List",
                          "children": {
                              "path": "/clinics",
                              "componentId": "clinic_row_tpl",
                          },
                      },
                      {
                          "id": "clinic_row_tpl",
                          "component": "Row",
                          "children": ["clinic_name", "clinic_wait"],
                      },
                      {
                          "id": "clinic_name",
                          "component": "Text",
                          "text": {"path": "name"},
                      },
                      {
                          "id": "clinic_wait",
                          "component": "Text",
                          "text": {"path": "waitTime"},
                      },
                  ],
              },
          },
          {
              "version": "v0.9",
              "updateDataModel": {
                  "surfaceId": "clinic_comparison_surface",
                  "path": "/",
                  "value": {
                      "comparisonTitle": (
                          "Nearby Urgent & Specialty Care Centers"
                      ),
                      "clinics": [
                          {
                              "name": "Central Heart & Vascular Center",
                              "waitTime": "10 mins",
                          },
                          {
                              "name": "Northside Outpatient Pavilion",
                              "waitTime": "25 mins",
                          },
                      ],
                  },
              },
          },
      ]
      GLOBAL_TRACE_RECORDER.record_span(
          span_name="generate_content [pattern1_dynamic_ui]",
          agent_name="care_comparison_dynamic_ui_agent",
          operation_name="generate_content",
          duration_ms=42.5,
          **{
              "gen_ai.usage.input_tokens": 310,
              "gen_ai.usage.output_tokens": 245,
          },
      )
      yield LlmResponse(
          usage_metadata=_usage(310, 245),
          content=types.Content(
              role="model",
              parts=[
                  types.Part.from_text(
                      text=(
                          "Here is a live comparison of nearby care centers:\n"
                          f"{A2UI_OPEN_TAG}{json.dumps(dynamic_envelopes)}{A2UI_CLOSE_TAG}"
                      )
                  )
              ],
          ),
      )
      return

    # 2. Pattern 3 & Remote Agent 1 (Triage Specialist with Self-Healing Validation)
    if self.role_name in ("pattern3_self_healing", "remote_triage_a2ui"):
      if not fn_responses:
        if self.role_name == "pattern3_self_healing":
          # Deliberately omit `"id": "root"` on first attempt to demonstrate Pattern 3 self-healing!
          broken_envelopes = [
              {
                  "version": "v0.9",
                  "createSurface": {
                      "surfaceId": "triage_intake_surface_01",
                      "catalogId": CARE_PORTAL_CATALOG_ID,
                      "sendDataModel": True,
                  },
              },
              {
                  "version": "v0.9",
                  "updateComponents": {
                      "surfaceId": "triage_intake_surface_01",
                      "components": [
                          {
                              "id": "wrong_entry_id_not_root",
                              "component": "TriageIntakeCard",
                              "urgency": {"path": "/urgency"},
                          }
                      ],
                  },
              },
          ]
          GLOBAL_TRACE_RECORDER.record_span(
              span_name="generate_content [triage_attempt_1_invalid_json]",
              agent_name="triage_specialist_service",
              operation_name="generate_content",
              duration_ms=34.0,
              **{
                  "gen_ai.usage.input_tokens": 280,
                  "gen_ai.usage.output_tokens": 115,
              },
          )
          yield LlmResponse(
              usage_metadata=_usage(280, 115),
              content=types.Content(
                  role="model",
                  parts=[
                      types.Part.from_function_call(
                          name="send_a2ui_json_to_client",
                          args={"a2ui_json": json.dumps(broken_envelopes)},
                      )
                  ],
              ),
          )
          return

      # Either second attempt (after validator caught missing `"id": "root"`) OR normal Remote Agent 1 call
      if not fn_responses or A2UI_ERROR_KEY in (fn_responses[0].response or {}):
        valid_triage_envelopes = [
            {
                "version": "v0.9",
                "createSurface": {
                    "surfaceId": "triage_intake_surface_01",
                    "catalogId": CARE_PORTAL_CATALOG_ID,
                    "theme": {
                        "primaryColor": "#028090",
                        "agentDisplayName": "Care Concierge - Clinical Triage",
                    },
                    "sendDataModel": True,
                },
            },
            {
                "version": "v0.9",
                "updateComponents": {
                    "surfaceId": "triage_intake_surface_01",
                    "components": [
                        {
                            "id": "root",
                            "component": "TriageIntakeCard",
                            "urgency": {"path": "/urgencyLevel"},
                            "specialty": {"path": "/recommendedSpecialty"},
                            "protocol": {"path": "/clinicalProtocol"},
                        }
                    ],
                },
            },
            {
                "version": "v0.9",
                "updateDataModel": {
                    "surfaceId": "triage_intake_surface_01",
                    "path": "/",
                    "value": {
                        "urgencyLevel": "PRIORITY_24H",
                        "recommendedSpecialty": "Interventional Cardiology",
                        "clinicalProtocol": "ACS-OUTPATIENT-PATHWAY-01",
                        "symptomNotes": (
                            "Exertional chest tightness & dyspnea"
                        ),
                    },
                },
            },
        ]
        GLOBAL_TRACE_RECORDER.record_span(
            span_name="generate_content [triage_valid_a2ui_tool_call]",
            agent_name="triage_specialist_service",
            operation_name="generate_content",
            duration_ms=36.2,
            **{
                "gen_ai.usage.input_tokens": 340,
                "gen_ai.usage.output_tokens": 160,
            },
        )
        yield LlmResponse(
            usage_metadata=_usage(340, 160),
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_call(
                        name="send_a2ui_json_to_client",
                        args={
                            "a2ui_json": json.dumps(valid_triage_envelopes)
                        },
                    )
                ],
            ),
        )
        return

    # 3. Pattern 2 & Remote Agent 2 (Scheduling Specialist calling Deterministic Tool)
    if self.role_name == "remote_scheduling_a2ui":
      if not fn_responses:
        GLOBAL_TRACE_RECORDER.record_span(
            span_name="generate_content [scheduling_select_tool]",
            agent_name="scheduling_specialist_service",
            operation_name="generate_content",
            duration_ms=28.4,
            **{
                "gen_ai.usage.input_tokens": 195,
                "gen_ai.usage.output_tokens": 22,
            },
        )
        yield LlmResponse(
            usage_metadata=_usage(195, 22),
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_call(
                        name="render_appointment_slot_picker",
                        args={"preferred_window": "Next Priority 24h Window"},
                    )
                ],
            ),
        )
        return

    # 4. Root Single-Voice Persona Consolidator (`concierge_root_voice`)
    if self.role_name == "concierge_root_voice":
      GLOBAL_TRACE_RECORDER.record_span(
          span_name="generate_content [concierge_root_single_voice]",
          agent_name="concierge_root_voice_agent",
          operation_name="generate_content",
          duration_ms=39.1,
          **{
              "gen_ai.usage.input_tokens": 260,
              "gen_ai.usage.output_tokens": 75,
          },
      )
      yield LlmResponse(
          usage_metadata=_usage(260, 75),
          content=types.Content(
              role="model",
              parts=[
                  types.Part.from_text(
                      text=(
                          "I've coordinated with our clinical triage and"
                          " scheduling specialists. Based on your symptoms and"
                          " cardiac watch history, we've prioritized an"
                          " Interventional Cardiology visit for you within 24"
                          " hours. Please review your triage summary card and"
                          " confirm your preferred appointment time below - your"
                          " Premier EPO copay is $25.00."
                      )
                  )
              ],
          ),
      )
      return

    # 5. Unified Playground Root (`concierge_playground_root`)
    if self.role_name == "concierge_playground_root":
      last_text = ""
      if llm_request.contents and llm_request.contents[-1].parts:
        last_text = (llm_request.contents[-1].parts[0].text or "").lower()
      if not fn_responses:
        if "wait time" in last_text or "compare" in last_text:
          yield LlmResponse(
              usage_metadata=_usage(220, 35),
              content=types.Content(
                  role="model",
                  parts=[
                      types.Part.from_function_call(
                          name="render_dynamic_wait_time_comparison",
                          args={"specialty": "Cardiology"},
                      )
                  ],
              ),
          )
          return
        if "slot" in last_text and "triage" not in last_text:
          yield LlmResponse(
              usage_metadata=_usage(210, 30),
              content=types.Content(
                  role="model",
                  parts=[
                      types.Part.from_function_call(
                          name="render_appointment_slot_picker_ge",
                          args={"preferred_window": "Next Priority 24h Window"},
                      )
                  ],
              ),
          )
          return
        yield LlmResponse(
            usage_metadata=_usage(250, 45),
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_function_call(
                        name="run_multiagent_a2a_triage_and_scheduling",
                        args={
                            "symptom_description": (
                                last_text
                                or "Chest tightness on exertion; need priority cardiology triage and slots."
                            )
                        },
                    )
                ],
            ),
        )
        return
      else:
        resp_dict = fn_responses[0].response or {}
        a2ui_block = resp_dict.get("a2ui_json_tag_block", "")
        result_str = resp_dict.get("result", "")
        body = a2ui_block or result_str
        yield LlmResponse(
            usage_metadata=_usage(290, 85),
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            "I've coordinated with our clinical triage and"
                            " scheduling specialists in a single unified voice."
                            " Please review your interactive A2UI v0.9"
                            f" surfaces below:\n{body}"
                        )
                    )
                ],
            ),
        )
        return

    yield LlmResponse(
        usage_metadata=_usage(10, 5),
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text="Completed turn.")],
        ),
    )


def get_model(
    role_name: str,
    offline_mock: bool = False,
) -> str | BaseLlm:
  if offline_mock or os.environ.get("OFFLINE_MOCK", "").lower() in (
      "1",
      "true",
  ):
    return OfflineDeterministicA2uiLlm(role_name=role_name)
  return os.environ.get("ADK_GEMINI_MODEL", "gemini-2.5-flash")
