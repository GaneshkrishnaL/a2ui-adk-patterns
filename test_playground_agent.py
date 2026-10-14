# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
"""Verification test for `concierge_a2ui_agent.agent.root_agent`."""

from __future__ import annotations

import asyncio
import json
import os

os.environ["A2UI_OFFLINE_MOCK"] = "1"

from concierge_a2ui_agent.agent import root_agent
from google.adk.runners import InMemoryRunner
from google.genai import types


async def verify_playground_root_agent() -> None:
  runner = InMemoryRunner(
      agent=root_agent, app_name="concierge_a2ui_agent"
  )
  await runner.session_service.create_session(
      app_name="concierge_a2ui_agent",
      user_id="cloud_console_user",
      session_id="sess_playground_01",
  )

  prompts = [
      (
          "Turn 1 (Pattern 1 - Dynamic Wait Time Comparison)",
          "Compare wait times across regional cardiology care centers.",
      ),
      (
          "Turn 2 (Pattern 2 - Deterministic Slot Picker with skip_summarization=True)",
          "Show me available priority appointment slots.",
      ),
      (
          "Turn 3 (Pattern 5 - Multi-Agent A2A Triage + Scheduling + Privacy Audit)",
          "I have chest tightness on exertion. Please triage my symptoms and coordinate priority slots.",
      ),
      (
          "Turn 4 (Pattern 4 - Zero-LLM Client Action Short-Circuit via before_model_callback)",
          json.dumps({
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
          }),
      ),
  ]

  for label, text in prompts:
    print(f"\n=== {label} ===")
    async for event in runner.run_async(
        user_id="cloud_console_user",
        session_id="sess_playground_01",
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text=text)]
        ),
    ):
      if event.content and event.content.parts:
        for p in event.content.parts:
          if p.text:
            print(f"  [Model Text]: {p.text[:220]}...")
          elif p.function_call:
            print(f"  [Tool Call]: {p.function_call.name}({p.function_call.args})")

  sess = await runner.session_service.get_session(
      app_name="concierge_a2ui_agent",
      user_id="cloud_console_user",
      session_id="sess_playground_01",
  )
  assert sess.state.get("a2ui_surface_id_triage_intake_surface_01") == (
      "triage_specialist_agent"
  )
  assert sess.state.get("a2ui_surface_id_slot_picker_surface_02") == (
      "scheduling_specialist_agent"
  )
  assert sess.state.get("privacy_audit_log", {}).get(
      "confidentialTriageSurfaceStripped"
  ) is True
  assert sess.state.get("last_routed_action_owner") == (
      "scheduling_specialist_agent"
  )
  print("\nALL PLAYGROUND AGENT ENGINE CHECKS PASSED!")


if __name__ == "__main__":
  asyncio.run(verify_playground_root_agent())
