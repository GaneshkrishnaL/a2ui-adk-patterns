# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# End-to-End Runnable Demo:
#   All 5 A2UI (Agent-to-UI) Production Patterns + Single-Voice Multi-Agent A2A
#   Orchestration (`A2uiSubagentMap`) + Cloud Trace OpenTelemetry Waterfall
#
# Usage:
#   1. Offline Deterministic Mode (zero external credentials required):
#      ./.venv/bin/python run_demo.py --offline-mock
#   2. Vertex AI Live LLM Mode (`gemini-2.5-flash`):
#      ./.venv/bin/python run_demo.py
#   3. Separate Live Uvicorn HTTP Servers (Ports 8011 & 8012):
#      ./run_live_servers.sh

from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import sys
import warnings

warnings.filterwarnings("ignore", message=".*EXPERIMENTAL.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent / "concierge_a2ui_agent"))

from a2ui_orchestration_bridge import A2uiSubagentMap
from a2ui_orchestration_bridge import GLOBAL_TRACE_RECORDER
from a2ui_orchestration_bridge import make_a2ui_and_output_key_interceptor
from a2ui_orchestration_bridge import make_a2ui_state_and_trace_meta_provider
from catalog_and_schema import A2uiPartConverter
from catalog_and_schema import CARE_PORTAL_CATALOG_ID
from google.adk.a2a import _compat as a2a_compat
from google.adk.a2a.agent.config import A2aRemoteAgentConfig
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
import httpx
from mock_llm import get_model
from remote_a2ui_agents import build_pattern1_dynamic_ui_agent
from remote_a2ui_agents import build_remote_scheduling_a2ui_agent
from remote_a2ui_agents import create_remote_scheduling_a2ui_app
from remote_a2ui_agents import create_remote_triage_a2ui_app
from remote_a2ui_agents import send_a2ui_json_to_client


def _print_a2a_parts(label: str, genai_parts: list[types.Part]) -> None:
  """Converts GenAI parts via `A2uiPartConverter` and prints A2A `TextPart` and `DataPart`s."""
  converter = A2uiPartConverter(
      fallback_text="Unable to render interactive surface."
  )
  a2a_parts = []
  for gp in genai_parts:
    a2a_parts.extend(converter.convert(gp))

  print(f"\n  [{label}] Converted into {len(a2a_parts)} A2A Wire Part(s):")
  for idx, p in enumerate(a2a_parts, start=1):
    if a2a_compat.is_text_part(p):
      print(f"    • Part #{idx} [A2A TextPart]: {a2a_compat.part_text(p)!r}")
    elif a2a_compat.is_data_part(p):
      meta = a2a_compat.part_metadata(p) or {}
      data_dict = a2a_compat.data_part_dict(p) or {}
      mime = meta.get("mimeType")
      action_keys = [k for k in data_dict.keys() if k != "version"]
      print(
          f"    • Part #{idx} [A2A DataPart | mimeType={mime!r} |"
          f" envelope={action_keys}]:\n"
          f"      {json.dumps(data_dict)}"
      )


async def run_all_5_patterns(
    live_http: bool = False,
    offline_mock: bool = False,
) -> None:
  # ==========================================================================
  # PATTERN 1: Prompt-Driven Dynamic LLM UI (`A2uiSchemaManager` + Stream Tag)
  # ==========================================================================
  print("\n" + "=" * 92)
  print(
      "PATTERN 1: PROMPT-DRIVEN DYNAMIC LLM UI GENERATION"
      " (`<a2ui-json>` + Collection Child Scope)"
  )
  print("=" * 92)
  p1_agent = build_pattern1_dynamic_ui_agent(offline_mock=offline_mock)
  p1_runner = InMemoryRunner(agent=p1_agent, app_name="pattern1_app")
  await p1_runner.session_service.create_session(
      app_name="pattern1_app", user_id="user_01", session_id="sess_p1"
  )
  async for event in p1_runner.run_async(
      user_id="user_01",
      session_id="sess_p1",
      new_message=types.Content(
          role="user",
          parts=[
              types.Part.from_text(
                  text="Compare wait times at nearby specialty care centers."
              )
          ],
      ),
  ):
    if event.content and event.content.parts:
      _print_a2a_parts("Pattern 1 Output", event.content.parts)

  # ==========================================================================
  # PATTERN 2: Deterministic Tool-Driven UI (`<a2ui-json>` + `skip_summarization=True`)
  # ==========================================================================
  print("\n" + "=" * 92)
  print(
      "PATTERN 2: TOOL-DRIVEN DETERMINISTIC UI TEMPLATE"
      " (`skip_summarization=True` -> Zero Post-Tool LLM Cost)"
  )
  print("=" * 92)
  p2_agent = build_remote_scheduling_a2ui_agent(offline_mock=offline_mock)
  p2_runner = InMemoryRunner(agent=p2_agent, app_name="pattern2_app")
  await p2_runner.session_service.create_session(
      app_name="pattern2_app",
      user_id="user_01",
      session_id="sess_p2",
      state={
          "member_id": "MEM-99412",
          "facility_id": "FACILITY-CENTRAL-01",
          "plan_tier": "PREMIER_EPO",
      },
  )
  async for event in p2_runner.run_async(
      user_id="user_01",
      session_id="sess_p2",
      new_message=types.Content(
          role="user",
          parts=[
              types.Part.from_text(
                  text="Show me available cardiology appointment slots."
              )
          ],
      ),
  ):
    if event.content and event.content.parts:
      has_fn_resp = any(p.function_response for p in event.content.parts)
      if has_fn_resp:
        print(
            f"\n  [ADK Event Actions] `event.actions.skip_summarization`"
            f" = {event.actions.skip_summarization}"
        )
        _print_a2a_parts(
            "Pattern 2 Deterministic Tool Output", event.content.parts
        )

  # ==========================================================================
  # PATTERN 3: Validated & Self-Healing Toolset (`SendA2uiToClientToolset`)
  # ==========================================================================
  print("\n" + "=" * 92)
  print(
      "PATTERN 3: SELF-HEALING A2UI TOOLSET VALIDATOR"
      " (Catches Missing `id='root'` & Auto-Repairs on Retry)"
  )
  print("=" * 92)
  p3_agent = LlmAgent(
      name="self_healing_triage_agent",
      model=get_model("pattern3_self_healing", offline_mock=offline_mock),
      instruction=(
          "Emit a validated A2UI v0.9 TriageIntakeCard surface via"
          " `send_a2ui_json_to_client`."
      ),
      tools=[send_a2ui_json_to_client],
  )
  p3_runner = InMemoryRunner(agent=p3_agent, app_name="pattern3_app")
  await p3_runner.session_service.create_session(
      app_name="pattern3_app", user_id="user_01", session_id="sess_p3"
  )
  async for event in p3_runner.run_async(
      user_id="user_01",
      session_id="sess_p3",
      new_message=types.Content(
          role="user",
          parts=[
              types.Part.from_text(
                  text="Render my clinical triage intake card."
              )
          ],
      ),
  ):
    if event.content and event.content.parts:
      for p in event.content.parts:
        if p.function_response and "validated_a2ui_json" in (
            p.function_response.response or {}
        ):
          _print_a2a_parts(
              "Pattern 3 Repaired & Validated Output", event.content.parts
          )

  # ==========================================================================
  # PATTERN 4: Zero-LLM Action Short-Circuiting (`before_model_callback`)
  # ==========================================================================
  print("\n" + "=" * 92)
  print(
      "PATTERN 4: ZERO-LLM CLIENT ACTION SHORT-CIRCUITING"
      " (`before_model_callback` + `updateDataModel` Delta)"
  )
  print("=" * 92)
  client_button_action = {
      "version": "v0.9",
      "action": {
          "name": "confirm_appointment",
          "surfaceId": "slot_picker_surface_02",
          "sourceComponentId": "confirm_btn",
          "context": {
              "memberId": "MEM-99412",
              "selectedSlotId": "SLOT-TUE-0930",
              "estimatedCopay": "$25.00",
          },
      },
  }
  async for event in p2_runner.run_async(
      user_id="user_01",
      session_id="sess_p2",
      new_message=types.Content(
          role="user",
          parts=[types.Part.from_text(text=json.dumps(client_button_action))],
      ),
  ):
    if event.content and event.content.parts:
      _print_a2a_parts(
          "Pattern 4 Zero-LLM Short-Circuit Delta", event.content.parts
      )

  # ==========================================================================
  # PATTERN 5: Multi-Agent A2A + Single-Voice `concierge_root` + `A2uiSubagentMap`
  # ==========================================================================
  print("\n" + "=" * 92)
  print(
      "PATTERN 5: MULTI-AGENT A2A ORCHESTRATION, SINGLE VOICE, SURFACE"
      " OWNERSHIP & DATA MODEL PRIVACY (`A2uiSubagentMap`)"
  )
  print("=" * 92)

  async with AsyncExitStack() as stack:
    if live_http:
      print(
          "Connecting to external A2A HTTP servers at http://localhost:8011 and"
          " http://localhost:8012"
      )
      client_1 = await stack.enter_async_context(
          httpx.AsyncClient(timeout=60.0)
      )
      client_2 = await stack.enter_async_context(
          httpx.AsyncClient(timeout=60.0)
      )
    else:
      print(
          "Starting Remote A2A Triage Agent (port 8011) & Remote A2A Scheduling"
          " Agent (port 8012) via in-process ASGI transport"
      )
      app_1 = create_remote_triage_a2ui_app(offline_mock=offline_mock)
      app_2 = create_remote_scheduling_a2ui_app(offline_mock=offline_mock)
      await stack.enter_async_context(app_1.router.lifespan_context(app_1))
      await stack.enter_async_context(app_2.router.lifespan_context(app_2))
      client_1 = await stack.enter_async_context(
          httpx.AsyncClient(
              transport=httpx.ASGITransport(app=app_1),
              base_url="http://localhost:8011",
              timeout=60.0,
          )
      )
      client_2 = await stack.enter_async_context(
          httpx.AsyncClient(
              transport=httpx.ASGITransport(app=app_2),
              base_url="http://localhost:8012",
              timeout=60.0,
          )
      )

    remote_triage = RemoteA2aAgent(
        name="triage_specialist_agent",
        description="Remote A2A Triage Specialist (Port 8011)",
        agent_card=f"http://localhost:8011{AGENT_CARD_WELL_KNOWN_PATH}",
        httpx_client=client_1,
        a2a_request_meta_provider=make_a2ui_state_and_trace_meta_provider(
            target_subagent_name="triage_specialist_agent",
            state_keys=["member_id", "facility_id", "clinical_flags"],
        ),
        config=A2aRemoteAgentConfig(
            forward_session_id_as_context_id=True,
            request_interceptors=[
                make_a2ui_and_output_key_interceptor(
                    subagent_name="triage_specialist_agent",
                    output_key="triage_output",
                )
            ],
        ),
    )

    remote_scheduling = RemoteA2aAgent(
        name="scheduling_specialist_agent",
        description="Remote A2A Scheduling & Benefits Specialist (Port 8012)",
        agent_card=f"http://localhost:8012{AGENT_CARD_WELL_KNOWN_PATH}",
        httpx_client=client_2,
        a2a_request_meta_provider=make_a2ui_state_and_trace_meta_provider(
            target_subagent_name="scheduling_specialist_agent",
            state_keys=[
                "member_id",
                "facility_id",
                "plan_tier",
                "triage_output",
            ],
        ),
        config=A2aRemoteAgentConfig(
            forward_session_id_as_context_id=True,
            request_interceptors=[
                make_a2ui_and_output_key_interceptor(
                    subagent_name="scheduling_specialist_agent",
                    output_key="scheduling_output",
                )
            ],
        ),
    )

    # Single-Voice Root Persona Agent (`concierge_root_voice_agent`)
    # Speaks in a unified, empathetic persona while passing through A2UI surfaces!
    concierge_voice_agent = LlmAgent(
        name="concierge_root_voice_agent",
        model=get_model("concierge_root_voice", offline_mock=offline_mock),
        description=(
            "Single-Voice Care Concierge Persona that synthesizes prose while"
            " passing through specialist A2UI surfaces."
        ),
        instruction=(
            "You are the unified Care Concierge voice. Present a warm,"
            " cohesive message for Member {member_id} summarizing"
            " `{triage_output}` and `{scheduling_output}` while the"
            " interactive A2UI surfaces render below."
        ),
        output_key="concierge_single_voice_response",
    )

    concierge_root = SequentialAgent(
        name="concierge_root",
        sub_agents=[
            remote_triage,
            remote_scheduling,
            concierge_voice_agent,
        ],
    )

    orch_runner = InMemoryRunner(
        agent=concierge_root, app_name="concierge_multiagent_a2ui"
    )
    user_id = "member_user_48291"
    session_id = "sess_multiagent_a2ui_005"

    # Seed client capabilities & multi-surface client data model to prove privacy stripping!
    initial_state = {
        "member_id": "MEM-99412",
        "facility_id": "FACILITY-CENTRAL-01",
        "clinical_flags": "History of hypertension; active cardiac watch",
        "plan_tier": "PREMIER_EPO",
        "a2ui_client_capabilities": {
            "supportedCatalogIds": [CARE_PORTAL_CATALOG_ID]
        },
        # Pre-seed an existing clinical surface in the client data model to verify
        # that `strip_unowned_surfaces_from_data_model` strips it when calling Scheduling!
        "a2ui_surface_id_triage_intake_surface_01": "triage_specialist_agent",
        "a2ui_client_data_model": {
            "version": "v0.9",
            "surfaces": {
                "triage_intake_surface_01": {
                    "symptomNotes": "CONFIDENTIAL CLINICAL TRIAGE NOTES",
                    "urgencyLevel": "PRIORITY_24H",
                }
            },
        },
    }

    await orch_runner.session_service.create_session(
        app_name="concierge_multiagent_a2ui",
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    async for _ in orch_runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=(
                        "I have chest tightness on exertion. Please triage my"
                        " symptoms and show me priority cardiology slots."
                    )
                )
            ],
        ),
    ):
      pass

    final_session = await orch_runner.session_service.get_session(
        app_name="concierge_multiagent_a2ui",
        user_id=user_id,
        session_id=session_id,
    )

    # Verify deterministic multi-turn UI action routing via `A2uiSubagentMap`
    routed_owner = A2uiSubagentMap.get_subagent_name_for_action(
        action_envelope=client_button_action,
        session_state=final_session.state,
    )

    print("\n" + "-" * 92)
    print(
        "SINGLE-VOICE `concierge_root` RESPONSE + PASSTHROUGH A2UI SURFACES"
        " DELIVERED TO CLIENT:"
    )
    print("-" * 92)
    print(
        f"  [Unified Voice Text]:\n   "
        f" {final_session.state.get('concierge_single_voice_response')}\n"
    )
    passthrough = final_session.state.get("passthrough_a2ui_envelopes", [])
    print(
        f"  [Passthrough A2UI Envelopes Emitted Across A2A]:"
        f" {len(passthrough)} envelope messages"
    )
    print(
        "  [Surface Ownership Registry in `session.state` (`A2uiSubagentMap`)]:"
    )
    print(
        "    • a2ui_surface_id_triage_intake_surface_01 ->"
        f" {final_session.state.get('a2ui_surface_id_triage_intake_surface_01')!r}"
    )
    print(
        "    • a2ui_surface_id_slot_picker_surface_02   ->"
        f" {final_session.state.get('a2ui_surface_id_slot_picker_surface_02')!r}"
    )
    print(
        "  [Deterministic Multi-Turn UI Action Routing Check]:\n"
        "    • Incoming click `confirm_appointment` on"
        f" `slot_picker_surface_02` routed to -> {routed_owner!r}"
    )

    # Print Agenda Item 2: Live Cloud Trace / OpenTelemetry Waterfall & Token Audit
    GLOBAL_TRACE_RECORDER.print_waterfall(conversation_id=session_id)


def test_run_all_5_patterns() -> None:
  """Pytest entrypoint."""
  asyncio.run(run_all_5_patterns(live_http=False, offline_mock=True))


def main() -> None:
  parser = argparse.ArgumentParser(
      description=(
          "Run All 5 A2UI Production Patterns + Multi-Agent A2A Orchestration"
          " & Cloud Trace Waterfall."
      )
  )
  parser.add_argument(
      "--live-http",
      action="store_true",
      help=(
          "Connect over TCP sockets to http://localhost:8011 and"
          " http://localhost:8012 (start with ./run_live_servers.sh)."
      ),
  )
  parser.add_argument(
      "--offline-mock",
      action="store_true",
      help="Run deterministically offline without calling Vertex AI.",
  )
  args = parser.parse_args()
  asyncio.run(
      run_all_5_patterns(
          live_http=args.live_http, offline_mock=args.offline_mock
      )
  )


if __name__ == "__main__":
  main()
