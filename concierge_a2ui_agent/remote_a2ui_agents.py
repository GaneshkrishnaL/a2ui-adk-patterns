# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# A2UI patterns 1 to 4 and the two remote A2A specialist agents (ports 8011 and 8012).

from __future__ import annotations

import json
import os
import time
from typing import Any
import warnings

os.environ.setdefault("ADK_SUPPRESS_A2A_EXPERIMENTAL_FEATURE_WARNINGS", "TRUE")
warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

from a2ui_orchestration_bridge import GLOBAL_TRACE_RECORDER
from a2ui_orchestration_bridge import state_and_a2ui_request_converter
from catalog_and_schema import A2UI_CLOSE_TAG
from catalog_and_schema import A2UI_ERROR_KEY
from catalog_and_schema import A2UI_OPEN_TAG
from catalog_and_schema import A2UI_VALIDATED_KEY
from catalog_and_schema import CARE_PORTAL_CATALOG_ID
from catalog_and_schema import generate_a2ui_system_prompt
from catalog_and_schema import parse_and_fix_a2ui_json
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutorConfig
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from mock_llm import get_model
from starlette.applications import Starlette


# ============================================================================
# PATTERN 1: Prompt-Driven Dynamic LLM UI (`A2uiSchemaManager` style)
# ============================================================================


def build_pattern1_dynamic_ui_agent(offline_mock: bool = False) -> LlmAgent:
  """Pattern 1: Injects catalog schema instructions into `LlmAgent.instruction`."""
  return LlmAgent(
      name="care_comparison_dynamic_ui_agent",
      model=get_model("pattern1_dynamic_ui", offline_mock=offline_mock),
      description=(
          "Generates ad-hoc dynamic A2UI comparison cards from prompt schema."
      ),
      instruction=generate_a2ui_system_prompt(
          role_description=(
              "You are a Care Navigation Assistant. Compare clinics and emit a"
              " dynamic A2UI v0.9 Card surface (`clinic_comparison_surface`)."
          ),
          ui_description=(
              "Render a `Card` with a `Column` of clinic options bound to"
              " `/clinics`."
          ),
      ),
  )


# ============================================================================
# PATTERN 2: Tool-Driven Deterministic UI (`<a2ui-json>` + `skip_summarization=True`)
# ============================================================================


def render_appointment_slot_picker(
    preferred_window: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 2: Populates a deterministic A2UI v0.9 template and skips LLM post-summarization."""
  t0 = time.perf_counter()
  member_id = tool_context.state.get("member_id", "MEM-99412")
  facility_id = tool_context.state.get("facility_id", "FACILITY-CENTRAL-01")
  plan_tier = tool_context.state.get("plan_tier", "PREMIER_EPO")
  triage_output = tool_context.state.get(
      "triage_output", "Priority Cardiology Referral"
  )
  copay = "$25.00" if plan_tier == "PREMIER_EPO" else "$60.00"

  # Deterministic A2UI v0.9 Envelope Array (createSurface + updateComponents + updateDataModel)
  a2ui_envelopes = [
      {
          "version": "v0.9",
          "createSurface": {
              "surfaceId": "slot_picker_surface_02",
              "catalogId": CARE_PORTAL_CATALOG_ID,
              "theme": {
                  "primaryColor": "#028090",
                  "agentDisplayName": "Care Concierge - Scheduling",
              },
              "sendDataModel": True,
          },
      },
      {
          "version": "v0.9",
          "updateComponents": {
              "surfaceId": "slot_picker_surface_02",
              "components": [
                  {
                      "id": "root",
                      "component": "AppointmentSlotPickerCard",
                      "children": [
                          "header_text",
                          "copay_badge",
                          "slot_choice",
                          "confirm_btn",
                      ],
                  },
                  {
                      "id": "header_text",
                      "component": "Text",
                      "text": {"path": "/providerBanner"},
                      "variant": "h3",
                  },
                  {
                      "id": "copay_badge",
                      "component": "CopaySummaryBadge",
                      "planTier": {"path": "/planTier"},
                      "estimatedCopay": {"path": "/estimatedCopay"},
                  },
                  {
                      "id": "slot_choice",
                      "component": "ChoicePicker",
                      "label": "Select Available Priority Slot",
                      "options": {"path": "/availableSlots"},
                      "value": {"path": "/selectedSlotId"},
                  },
                  {
                      "id": "confirm_btn",
                      "component": "Button",
                      "label": "Confirm Appointment",
                      "variant": "primary",
                      "checks": [
                          {
                              "condition": {
                                  "call": "required",
                                  "args": {
                                      "value": {"path": "/selectedSlotId"}
                                  },
                              },
                              "message": (
                                  "Please select a time slot before confirming."
                              ),
                          }
                      ],
                      "action": {
                          "event": {
                              "name": "confirm_appointment",
                              "context": {
                                  "memberId": member_id,
                                  "selectedSlotId": {
                                      "path": "/selectedSlotId"
                                  },
                                  "estimatedCopay": {
                                      "path": "/estimatedCopay"
                                  },
                              },
                          }
                      },
                  },
              ],
          },
      },
      {
          "version": "v0.9",
          "updateDataModel": {
              "surfaceId": "slot_picker_surface_02",
              "path": "/",
              "value": {
                  "memberId": member_id,
                  "facilityId": facility_id,
                  "planTier": plan_tier,
                  "estimatedCopay": copay,
                  "triageBasis": triage_output,
                  "bookingStatus": "PENDING_SELECTION",
                  "providerBanner": (
                      f"Dr. Sarah Jenkins, MD - Cardiology ({facility_id})"
                  ),
                  "selectedSlotId": "SLOT-TUE-0930",
                  "availableSlots": [
                      {
                          "id": "SLOT-TUE-0930",
                          "label": "Tomorrow 09:30 AM (In-Person)",
                      },
                      {
                          "id": "SLOT-TUE-1400",
                          "label": "Tomorrow 02:00 PM (Telehealth)",
                      },
                  ],
              },
          },
      },
  ]

  # CRITICAL FOR PRODUCTION: Skip the post-tool LLM summarization pass so the
  # LLM never corrupts the deterministic JSON or burns 1,500 output tokens!
  tool_context.actions.skip_summarization = True

  elapsed_ms = (time.perf_counter() - t0) * 1000.0 + 0.6
  GLOBAL_TRACE_RECORDER.record_span(
      span_name="execute_tool [render_appointment_slot_picker]",
      agent_name="scheduling_specialist_service",
      operation_name="execute_tool",
      duration_ms=elapsed_ms,
      **{"a2ui.surfaces_emitted": ["slot_picker_surface_02"]},
  )

  summary_line = (
      f"Prepared priority appointment slot picker for {member_id} at"
      f" {facility_id} (Estimated Copay: {copay}, Window: {preferred_window})."
  )
  return {
      "result": (
          f"{summary_line}\n"
          f"{A2UI_OPEN_TAG}{json.dumps(a2ui_envelopes)}{A2UI_CLOSE_TAG}"
      )
  }


# ============================================================================
# PATTERN 3: Validated & Self-Healing Toolset (`send_a2ui_json_to_client`)
# ============================================================================


def send_a2ui_json_to_client(
    a2ui_json: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 3: Validates LLM-authored A2UI JSON; returns errors to LLM for self-repair if invalid!

  Mirrors `_SendA2uiJsonToClientTool.run_async` in `SendA2uiToClientToolset`:
    - If `a2ui_json` is valid: sets `tool_context.actions.skip_summarization = True`
      and returns `{validated_a2ui_json: [...]}` + `<a2ui-json>` tag.
    - If `a2ui_json` fails schema or root-id validation: leaves
      `skip_summarization = False` and returns `{a2ui_validation_error: "..."}`
      so the LLM immediately repairs the broken JSON on the next step!
  """
  t0 = time.perf_counter()
  try:
    validated_envelopes = parse_and_fix_a2ui_json(a2ui_json)
    tool_context.actions.skip_summarization = True
    elapsed_ms = (time.perf_counter() - t0) * 1000.0 + 0.5
    GLOBAL_TRACE_RECORDER.record_span(
        span_name="execute_tool [send_a2ui_json_to_client:VALID]",
        agent_name="triage_specialist_service",
        operation_name="execute_tool",
        duration_ms=elapsed_ms,
        **{"a2ui.validation": "PASSED"},
    )
    print(
        "\n  [Pattern 3 Toolset Validator] PASSED A2UI v0.9 schema validation!"
        " (`skip_summarization = True`)"
    )
    return {
        A2UI_VALIDATED_KEY: validated_envelopes,
        "result": (
            "[TRIAGE_SUMMARY] Urgency=PRIORITY_24H | Specialty=Interventional"
            " Cardiology | Protocol=ACS-PATHWAY-01\n"
            f"{A2UI_OPEN_TAG}{json.dumps(validated_envelopes)}{A2UI_CLOSE_TAG}"
        ),
    }
  except Exception as exc:  # pylint: disable=broad-except
    elapsed_ms = (time.perf_counter() - t0) * 1000.0 + 0.4
    GLOBAL_TRACE_RECORDER.record_span(
        span_name="execute_tool [send_a2ui_json_to_client:RETRY]",
        agent_name="triage_specialist_service",
        operation_name="execute_tool",
        duration_ms=elapsed_ms,
        **{"a2ui.validation": f"FAILED ({exc})"},
    )
    print(
        "\n  [Pattern 3 Toolset Validator] CAUGHT INVALID LLM A2UI JSON ->"
        f" Returning error to LLM for self-healing retry:\n    • {exc}"
    )
    return {
        A2UI_ERROR_KEY: (
            f"Failed to validate A2UI v0.9 JSON: {exc}. Please fix the JSON"
            " and call `send_a2ui_json_to_client` again."
        )
    }


# ============================================================================
# PATTERN 4: Zero-LLM Action Short-Circuiting (`before_model_callback`)
# ============================================================================


def short_circuit_a2ui_action_before_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
  """Pattern 4: Intercepts incoming client A2UI `action` events and updates data model with ZERO LLM calls!"""
  if not llm_request.contents:
    return None
  last_content = llm_request.contents[-1]
  if not last_content.parts:
    return None

  for part in last_content.parts:
    if not part.text or '"action"' not in part.text:
      continue
    try:
      payload = json.loads(part.text)
    except json.JSONDecodeError:
      continue

    action = payload.get("action")
    if (
        isinstance(action, dict)
        and action.get("name") == "confirm_appointment"
    ):
      t0 = time.perf_counter()
      surface_id = action.get("surfaceId", "slot_picker_surface_02")
      ctx_data = action.get("context", {})
      slot_id = ctx_data.get("selectedSlotId", "SLOT-TUE-0930")
      copay = ctx_data.get("estimatedCopay", "$25.00")
      confirmation_code = "CONF-88420-CARDIO"

      # Record state update in ADK session state
      callback_context.state["confirmed_booking"] = {
          "confirmation_code": confirmation_code,
          "slot_id": slot_id,
          "surface_id": surface_id,
      }

      # Emit a tiny A2UI v0.9 `updateDataModel` delta updating the existing surface in-place!
      delta_envelopes = [
          {
              "version": "v0.9",
              "updateDataModel": {
                  "surfaceId": surface_id,
                  "path": "/bookingStatus",
                  "value": "CONFIRMED",
              },
          },
          {
              "version": "v0.9",
              "updateDataModel": {
                  "surfaceId": surface_id,
                  "path": "/confirmationCode",
                  "value": confirmation_code,
              },
          },
      ]
      elapsed_ms = (time.perf_counter() - t0) * 1000.0 + 0.3
      GLOBAL_TRACE_RECORDER.record_span(
          span_name="before_model_callback [short_circuit_a2ui_action]",
          agent_name="scheduling_specialist_service",
          operation_name="short_circuit_action",
          duration_ms=elapsed_ms,
          **{
              "gen_ai.usage.input_tokens": 0,
              "gen_ai.usage.output_tokens": 0,
              "a2ui.surfaces_emitted": [surface_id],
          },
      )
      print(
          "\n  [Pattern 4 Zero-LLM Short-Circuit] Intercepted"
          f" `confirm_appointment` on '{surface_id}' in `before_model_callback`"
          " -> Bypassing LLM (0 tokens, <1ms)!"
      )
      return LlmResponse(
          usage_metadata=types.GenerateContentResponseUsageMetadata(
              prompt_token_count=0,
              candidates_token_count=0,
              total_token_count=0,
          ),
          content=types.Content(
              role="model",
              parts=[
                  types.Part.from_text(
                      text=(
                          f"Appointment confirmed ({confirmation_code}) for"
                          f" slot {slot_id} (Copay: {copay}).\n"
                          f"{A2UI_OPEN_TAG}{json.dumps(delta_envelopes)}{A2UI_CLOSE_TAG}"
                      )
                  )
              ],
          ),
      )
  return None


# ============================================================================
# REMOTE A2A AGENT 1 (Port 8011) & REMOTE A2A AGENT 2 (Port 8012)
# ============================================================================


def build_remote_triage_a2ui_agent(offline_mock: bool = False) -> LlmAgent:
  """Remote Agent 1: Uses Pattern 3 (`send_a2ui_json_to_client`) to emit validated `triage_intake_surface_01`."""
  return LlmAgent(
      name="triage_specialist_service",
      model=get_model("remote_triage_a2ui", offline_mock=offline_mock),
      description=(
          "Remote A2A Clinical Triage Specialist that evaluates symptoms and"
          " emits a validated A2UI TriageIntakeCard surface."
      ),
      instruction=(
          "You are the Clinical Triage Remote Specialist.\n"
          "Delegated Context:\n"
          "- Member ID: {member_id}\n"
          "- Facility ID: {facility_id}\n"
          "- Clinical Flags: {clinical_flags}\n"
          "Call `send_a2ui_json_to_client` to render surface"
          " `triage_intake_surface_01` using catalog"
          f" `{CARE_PORTAL_CATALOG_ID}`."
      ),
      tools=[send_a2ui_json_to_client],
  )


def build_remote_scheduling_a2ui_agent(offline_mock: bool = False) -> LlmAgent:
  """Remote Agent 2: Uses Pattern 2 (Deterministic Tool UI) + Pattern 4 (`before_model_callback` Short-Circuit)."""
  return LlmAgent(
      name="scheduling_specialist_service",
      model=get_model("remote_scheduling_a2ui", offline_mock=offline_mock),
      description=(
          "Remote A2A Scheduling & Benefits Specialist that emits"
          " `slot_picker_surface_02` and short-circuits button actions."
      ),
      instruction=(
          "You are the Scheduling & Benefits Remote Specialist.\n"
          "Call `render_appointment_slot_picker` to render the interactive"
          " appointment slot picker surface."
      ),
      tools=[render_appointment_slot_picker],
      before_model_callback=short_circuit_a2ui_action_before_model,
  )


def create_remote_triage_a2ui_app(
    host: str = "localhost",
    port: int = 8011,
    offline_mock: bool = False,
) -> Starlette:
  agent = build_remote_triage_a2ui_agent(offline_mock=offline_mock)

  def _executor_factory(runner: Runner) -> A2aAgentExecutor:
    return A2aAgentExecutor(
        runner=runner,
        config=A2aAgentExecutorConfig(
            request_converter=state_and_a2ui_request_converter
        ),
    )

  return to_a2a(
      agent,
      host=host,
      port=port,
      protocol="http",
      agent_executor_factory=_executor_factory,
  )


def create_remote_scheduling_a2ui_app(
    host: str = "localhost",
    port: int = 8012,
    offline_mock: bool = False,
) -> Starlette:
  agent = build_remote_scheduling_a2ui_agent(offline_mock=offline_mock)

  def _executor_factory(runner: Runner) -> A2aAgentExecutor:
    return A2aAgentExecutor(
        runner=runner,
        config=A2aAgentExecutorConfig(
            request_converter=state_and_a2ui_request_converter
        ),
    )

  return to_a2a(
      agent,
      host=host,
      port=port,
      protocol="http",
      agent_executor_factory=_executor_factory,
  )


agent1_app = create_remote_triage_a2ui_app()
agent2_app = create_remote_scheduling_a2ui_app()
