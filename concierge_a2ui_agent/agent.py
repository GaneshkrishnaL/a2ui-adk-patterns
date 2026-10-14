# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Entry point for `adk web`, `adk deploy agent_engine` and Gemini Enterprise.
# Exposes `root_agent` (the concierge_root orchestrator).

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional

# Ensure sibling modules resolve both inside Agent Engine container and locally
_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
  sys.path.insert(0, _PACKAGE_DIR)

from a2ui_orchestration_bridge import A2uiSubagentMap
from a2ui_orchestration_bridge import make_a2ui_and_output_key_interceptor
from a2ui_orchestration_bridge import make_a2ui_state_and_trace_meta_provider
from catalog_and_schema import A2UI_ERROR_KEY
from catalog_and_schema import A2UI_VALIDATED_KEY
from catalog_and_schema import CARE_PORTAL_A2UI_SCHEMA
from catalog_and_schema import CARE_PORTAL_CATALOG_ID
from catalog_and_schema import parse_and_fix_a2ui_json
from google.adk.a2a.agent.config import A2aRemoteAgentConfig
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools.tool_context import ToolContext
from google.genai import types
import httpx
from mock_llm import get_model
from remote_a2ui_agents import create_remote_scheduling_a2ui_app
from remote_a2ui_agents import create_remote_triage_a2ui_app

# Official Gemini Enterprise A2UI v0.9 Composite Catalog & DataPart Wire Format
GEMINI_ENTERPRISE_CATALOG_ID = (
    "https://www.gstatic.com/vertexaisearch/a2ui/v0_9/"
    "gemini_enterprise_composite_catalog.json"
)
A2UI_MIME_TYPE = "application/json+a2ui"
A2A_DATA_PART_START_TAG = "<a2a_datapart_json>"
A2A_DATA_PART_END_TAG = "</a2a_datapart_json>"
STAGED_A2UI_KEY = "_staged_a2ui_payloads"

_A2A_DATA_PART_STRIP_REGEX = re.compile(
    r"<a2a_datapart_json>.*?(?:</a2a_datapart_json>|$)",
    flags=re.DOTALL,
)
_USER_ACTION_TEXT_PATTERN = re.compile(
    r"User\s+Selected\s+Action:?\s*['\"]?([\w\-]+)['\"]?\s+with\s+Context:\s*(\{.*)",
    flags=re.IGNORECASE | re.DOTALL,
)


def create_a2ui_inline_parts(
    envelopes: Sequence[Mapping[str, Any]],
) -> list[types.Part]:
  """Wraps A2UI v0.9 surface envelopes into Gemini Enterprise `<a2a_datapart_json>` inline_data parts."""
  inline_parts: list[types.Part] = []
  for item in envelopes:
    if not isinstance(item, Mapping):
      continue
    final_item = {
        "kind": "data",
        "metadata": {"mimeType": A2UI_MIME_TYPE},
        "data": dict(item),
    }
    tagged_json = (
        f"{A2A_DATA_PART_START_TAG}"
        f"{json.dumps(final_item)}"
        f"{A2A_DATA_PART_END_TAG}"
    )
    inline_parts.append(
        types.Part(
            inline_data=types.Blob(
                data=tagged_json.encode("utf-8"),
                mime_type="text/plain",
            )
        )
    )
  return inline_parts


def _stage_a2ui_envelopes(
    state: Any,
    envelopes: list[dict[str, Any]],
    subagent_name: str = "concierge_root",
) -> None:
  """Stages A2UI v0.9 envelopes in session state for `after_model_a2ui_callback` and Visual Playground."""
  existing = list(state.get(STAGED_A2UI_KEY) or [])
  existing.extend(envelopes)
  state[STAGED_A2UI_KEY] = existing
  state["last_emitted_a2ui_envelopes"] = existing
  A2uiSubagentMap.update_from_envelopes(
      subagent_name=subagent_name,
      envelopes=envelopes,
      session_state=state,
  )


def build_surface_lock_message(
    surface_id: str,
    selected_id: str | None = None,
) -> dict[str, Any]:
  """Builds an A2UI v0.9 `updateDataModel` message setting `/disabled: True` to lock a card."""
  val: dict[str, Any] = {"disabled": True}
  if selected_id:
    val["selected_id"] = selected_id
  return {
      "version": "v0.9",
      "updateDataModel": {
          "surfaceId": surface_id,
          "path": "/",
          "value": val,
      },
  }


# ============================================================================
# GEMINI ENTERPRISE NATIVE `MaterialCard` SURFACE BUILDERS (Patterns 1-5)
# ============================================================================


def build_ge_wait_time_comparison_card(
    specialty: str = "Cardiology",
    member_id: str = "MEM-99412",
) -> list[dict[str, Any]]:
  """Pattern 1: Builds a Gemini Enterprise `MaterialCard` Wait-Time Comparison Table."""
  surface_id = "clinic_comparison_surface"
  prefix = "wait_cmp"
  facilities = [
      {
          "id": "FACILITY-CENTRAL-01",
          "slot_id": "SLOT-TUE-0930",
          "name": "Central Heart & Vascular Center",
          "wait": "12 mins (3 slots today)",
          "modality": "In-Person Specialty ($25 Copay)",
      },
      {
          "id": "FACILITY-NORTH-02",
          "slot_id": "SLOT-TUE-1115",
          "name": "Northside Medical Pavilion",
          "wait": "24 mins (5 slots today)",
          "modality": "In-Person Specialty ($25 Copay)",
      },
      {
          "id": "FACILITY-VIRTUAL-03",
          "slot_id": "SLOT-TUE-1400",
          "name": "Regional Virtual Care Hub",
          "wait": "5 mins (Immediate)",
          "modality": "Same-Day Telehealth ($0 Copay)",
      },
  ]

  components: list[dict[str, Any]] = [
      {
          "id": f"{prefix}_header_row",
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "8px"},
          "children": [f"{prefix}_title", f"{prefix}_badge"],
      },
      {
          "id": f"{prefix}_title",
          "component": "MaterialText",
          "text": f"Live {specialty.title()} Wait-Time Comparison",
          "usageHint": "h5",
      },
      {
          "id": f"{prefix}_badge",
          "component": "MaterialText",
          "text": f"{len(facilities)} Regional Centers",
          "usageHint": "caption",
      },
      {
          "id": f"{prefix}_subtitle",
          "component": "MaterialText",
          "text": (
              "Pattern 1 Dynamic A2UI Table Card • In-network Tier 1 specialty"
              " visits carry a $25 copay. Click Select Center on any row to"
              " book immediately."
          ),
          "usageHint": "body2",
      },
      {"id": f"{prefix}_header_div", "component": "MaterialDivider"},
      {
          "id": f"{prefix}_th_row",
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "16px"},
          "children": [
              f"{prefix}_th_0",
              f"{prefix}_th_1",
              f"{prefix}_th_2",
              f"{prefix}_th_3",
          ],
      },
      {
          "id": f"{prefix}_th_0",
          "component": "MaterialText",
          "text": "Care Center",
          "usageHint": "subtitle2",
          "weight": 2,
      },
      {
          "id": f"{prefix}_th_1",
          "component": "MaterialText",
          "text": "Live Wait Time",
          "usageHint": "subtitle2",
          "weight": 1,
      },
      {
          "id": f"{prefix}_th_2",
          "component": "MaterialText",
          "text": "Modality & Coverage",
          "usageHint": "subtitle2",
          "weight": 2,
      },
      {
          "id": f"{prefix}_th_3",
          "component": "MaterialText",
          "text": "Action",
          "usageHint": "subtitle2",
          "weight": 1,
      },
      {"id": f"{prefix}_th_div", "component": "MaterialDivider"},
  ]

  card_children = [
      f"{prefix}_header_row",
      f"{prefix}_subtitle",
      f"{prefix}_header_div",
      f"{prefix}_th_row",
      f"{prefix}_th_div",
  ]

  for idx, fac in enumerate(facilities):
    if idx > 0:
      div_id = f"{prefix}_row_div_{idx}"
      card_children.append(div_id)
      components.append({"id": div_id, "component": "MaterialDivider"})
    row_id = f"{prefix}_row_{idx}"
    c0, c1, c2, btn_id = (
        f"{prefix}_c_{idx}_0",
        f"{prefix}_c_{idx}_1",
        f"{prefix}_c_{idx}_2",
        f"{prefix}_btn_{idx}",
    )
    card_children.append(row_id)
    components.extend([
        {
            "id": row_id,
            "component": "MaterialRow",
            "justify": "spaceBetween",
            "align": "center",
            "style": {"gap": "16px"},
            "children": [c0, c1, c2, btn_id],
        },
        {
            "id": c0,
            "component": "MaterialText",
            "text": fac["name"],
            "usageHint": "body1",
            "weight": 2,
        },
        {
            "id": c1,
            "component": "MaterialText",
            "text": fac["wait"],
            "usageHint": "body2",
            "weight": 1,
        },
        {
            "id": c2,
            "component": "MaterialText",
            "text": fac["modality"],
            "usageHint": "body2",
            "weight": 2,
        },
        {
            "id": btn_id,
            "component": "MaterialButton",
            "label": "Select Center",
            "appearance": "tonal",
            "loadingOnClick": True,
            "disabled": {"path": "/disabled"},
            "action": {
                "event": {
                    "name": "confirm_appointment",
                    "context": {
                        "surface_id": surface_id,
                        "surfaceId": surface_id,
                        "memberId": member_id,
                        "selectedSlotId": fac["slot_id"],
                        "facilityId": fac["id"],
                        "facilityName": fac["name"],
                        "estimatedCopay": "$25.00",
                        "prompt": (
                            f"Confirm appointment at {fac['name']}"
                            f" ({fac['slot_id']})"
                        ),
                    },
                }
            },
        },
    ])

  all_components = [
      {
          "id": "root",
          "component": "MaterialCard",
          "appearance": "outlined",
          "style": {"marginBottom": "16px"},
          "children": card_children,
      },
      *components,
  ]
  return [
      {
          "version": "v0.9",
          "createSurface": {
              "surfaceId": surface_id,
              "catalogId": GEMINI_ENTERPRISE_CATALOG_ID,
              "sendDataModel": True,
          },
      },
      {
          "version": "v0.9",
          "updateComponents": {
              "surfaceId": surface_id,
              "components": all_components,
          },
      },
      {
          "version": "v0.9",
          "updateDataModel": {
              "surfaceId": surface_id,
              "path": "/",
              "value": {
                  "disabled": False,
                  "specialty": specialty,
                  "facilities": facilities,
              },
          },
      },
  ]


def build_ge_triage_intake_card(
    member_id: str = "MEM-99412",
    facility_id: str = "FACILITY-CENTRAL-01",
    clinical_flags: str = "History of hypertension; active cardiac watch",
) -> list[dict[str, Any]]:
  """Pattern 3: Builds a Gemini Enterprise `MaterialCard` Clinical Triage Assessment Card."""
  surface_id = "triage_intake_surface_01"
  prefix = "triage_card"
  rows = [
      ("Member ID", member_id),
      ("Clinical Pathway", "ACS-PATHWAY-01 (Interventional Cardiology)"),
      ("Urgency Level", "PRIORITY_24H (Within 24 Hours)"),
      ("Primary Facility", facility_id),
      ("Clinical Risk Flags", clinical_flags),
      (
          "Data Model Privacy",
          "Protected via A2uiSubagentMap (Stripped from non-owning agents)",
      ),
  ]

  components: list[dict[str, Any]] = [
      {
          "id": f"{prefix}_header_row",
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "8px"},
          "children": [f"{prefix}_title", f"{prefix}_badge"],
      },
      {
          "id": f"{prefix}_title",
          "component": "MaterialText",
          "text": "Clinical Triage & Risk Intake Card",
          "usageHint": "h5",
      },
      {
          "id": f"{prefix}_badge",
          "component": "MaterialText",
          "text": "PRIORITY_24H",
          "usageHint": "caption",
      },
      {
          "id": f"{prefix}_subtitle",
          "component": "MaterialText",
          "text": (
              "Pattern 3 Validated & Self-Healing A2UI Surface • Owned by"
              " triage_specialist_agent"
          ),
          "usageHint": "body2",
      },
      {"id": f"{prefix}_header_div", "component": "MaterialDivider"},
  ]
  card_children = [
      f"{prefix}_header_row",
      f"{prefix}_subtitle",
      f"{prefix}_header_div",
  ]

  for idx, (label, val) in enumerate(rows):
    if idx > 0:
      div_id = f"{prefix}_div_{idx}"
      card_children.append(div_id)
      components.append({"id": div_id, "component": "MaterialDivider"})
    row_id = f"{prefix}_row_{idx}"
    k_id = f"{prefix}_k_{idx}"
    v_id = f"{prefix}_v_{idx}"
    card_children.append(row_id)
    components.extend([
        {
            "id": row_id,
            "component": "MaterialRow",
            "justify": "spaceBetween",
            "align": "start",
            "style": {"gap": "16px"},
            "children": [k_id, v_id],
        },
        {
            "id": k_id,
            "component": "MaterialText",
            "text": label,
            "usageHint": "body2",
            "weight": 1,
        },
        {
            "id": v_id,
            "component": "MaterialText",
            "text": val,
            "usageHint": "body1",
            "weight": 2,
        },
    ])

  all_components = [
      {
          "id": "root",
          "component": "MaterialCard",
          "appearance": "outlined",
          "style": {"marginBottom": "16px"},
          "children": card_children,
      },
      *components,
  ]
  return [
      {
          "version": "v0.9",
          "createSurface": {
              "surfaceId": surface_id,
              "catalogId": GEMINI_ENTERPRISE_CATALOG_ID,
              "sendDataModel": True,
          },
      },
      {
          "version": "v0.9",
          "updateComponents": {
              "surfaceId": surface_id,
              "components": all_components,
          },
      },
      {
          "version": "v0.9",
          "updateDataModel": {
              "surfaceId": surface_id,
              "path": "/",
              "value": {
                  "disabled": False,
                  "memberId": member_id,
                  "urgencyLevel": "PRIORITY_24H",
                  "symptomNotes": "CONFIDENTIAL CLINICAL TRIAGE NOTES",
              },
          },
      },
  ]


def build_ge_slot_picker_card(
    preferred_window: str = "Tomorrow Morning",
    member_id: str = "MEM-99412",
    facility_id: str = "FACILITY-CENTRAL-01",
    plan_tier: str = "PREMIER_EPO",
    triage_output: str = "Priority Cardiology Referral (PRIORITY_24H)",
) -> list[dict[str, Any]]:
  """Pattern 2: Builds a Gemini Enterprise `MaterialCard` Interactive Appointment Slot Picker."""
  surface_id = "slot_picker_surface_02"
  prefix = "slot_picker"
  copay = "$25.00" if plan_tier == "PREMIER_EPO" else "$60.00"

  info_rows = [
      ("Provider", f"Dr. Sarah Jenkins, MD - Cardiology ({facility_id})"),
      ("Member ID & Plan", f"{member_id} • {plan_tier} (Copay: {copay})"),
      ("Clinical Referral Basis", str(triage_output)),
      ("Requested Window", preferred_window),
  ]

  slots = [
      {
          "slot_id": "SLOT-TUE-0930",
          "time": "Tomorrow 09:30 AM",
          "modality": "In-Person Cardiology Clinic",
          "copay": copay,
      },
      {
          "slot_id": "SLOT-TUE-1400",
          "time": "Tomorrow 02:00 PM",
          "modality": "Priority Video Telehealth",
          "copay": "$0.00",
      },
  ]

  components: list[dict[str, Any]] = [
      {
          "id": f"{prefix}_header_row",
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "8px"},
          "children": [f"{prefix}_title", f"{prefix}_badge"],
      },
      {
          "id": f"{prefix}_title",
          "component": "MaterialText",
          "text": "Priority Cardiology Appointment Slot Picker",
          "usageHint": "h5",
      },
      {
          "id": f"{prefix}_badge",
          "component": "MaterialText",
          "text": f"Copay: {copay}",
          "usageHint": "caption",
      },
      {
          "id": f"{prefix}_subtitle",
          "component": "MaterialText",
          "text": (
              "Pattern 2 Deterministic A2UI Card + Pattern 4 Zero-LLM Button"
              " Action • Click Book Slot or Confirm Priority Appointment below."
          ),
          "usageHint": "body2",
      },
      {"id": f"{prefix}_header_div", "component": "MaterialDivider"},
  ]
  card_children = [
      f"{prefix}_header_row",
      f"{prefix}_subtitle",
      f"{prefix}_header_div",
  ]

  for idx, (label, val) in enumerate(info_rows):
    if idx > 0:
      div_id = f"{prefix}_info_div_{idx}"
      card_children.append(div_id)
      components.append({"id": div_id, "component": "MaterialDivider"})
    row_id = f"{prefix}_info_row_{idx}"
    k_id = f"{prefix}_info_k_{idx}"
    v_id = f"{prefix}_info_v_{idx}"
    card_children.append(row_id)
    components.extend([
        {
            "id": row_id,
            "component": "MaterialRow",
            "justify": "spaceBetween",
            "align": "start",
            "style": {"gap": "16px"},
            "children": [k_id, v_id],
        },
        {
            "id": k_id,
            "component": "MaterialText",
            "text": label,
            "usageHint": "body2",
            "weight": 1,
        },
        {
            "id": v_id,
            "component": "MaterialText",
            "text": val,
            "usageHint": "body1",
            "weight": 2,
        },
    ])

  # Available Slots Table Section
  slots_div_id = f"{prefix}_slots_section_div"
  slots_th_row = f"{prefix}_slots_th_row"
  slots_th_div = f"{prefix}_slots_th_div"
  card_children.extend([slots_div_id, slots_th_row, slots_th_div])
  components.extend([
      {"id": slots_div_id, "component": "MaterialDivider"},
      {
          "id": slots_th_row,
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "16px"},
          "children": [
              f"{prefix}_sth_0",
              f"{prefix}_sth_1",
              f"{prefix}_sth_2",
              f"{prefix}_sth_3",
          ],
      },
      {
          "id": f"{prefix}_sth_0",
          "component": "MaterialText",
          "text": "Slot ID",
          "usageHint": "subtitle2",
          "weight": 1,
      },
      {
          "id": f"{prefix}_sth_1",
          "component": "MaterialText",
          "text": "Date & Time",
          "usageHint": "subtitle2",
          "weight": 2,
      },
      {
          "id": f"{prefix}_sth_2",
          "component": "MaterialText",
          "text": "Visit Modality",
          "usageHint": "subtitle2",
          "weight": 2,
      },
      {
          "id": f"{prefix}_sth_3",
          "component": "MaterialText",
          "text": "Action",
          "usageHint": "subtitle2",
          "weight": 1,
      },
      {"id": slots_th_div, "component": "MaterialDivider"},
  ])

  for s_idx, slot in enumerate(slots):
    if s_idx > 0:
      s_div = f"{prefix}_slot_div_{s_idx}"
      card_children.append(s_div)
      components.append({"id": s_div, "component": "MaterialDivider"})
    s_row = f"{prefix}_slot_row_{s_idx}"
    sc0 = f"{prefix}_sc_{s_idx}_0"
    sc1 = f"{prefix}_sc_{s_idx}_1"
    sc2 = f"{prefix}_sc_{s_idx}_2"
    sbtn = f"{prefix}_sbtn_{s_idx}"
    card_children.append(s_row)
    components.extend([
        {
            "id": s_row,
            "component": "MaterialRow",
            "justify": "spaceBetween",
            "align": "center",
            "style": {"gap": "16px"},
            "children": [sc0, sc1, sc2, sbtn],
        },
        {
            "id": sc0,
            "component": "MaterialText",
            "text": slot["slot_id"],
            "usageHint": "body2",
            "weight": 1,
        },
        {
            "id": sc1,
            "component": "MaterialText",
            "text": slot["time"],
            "usageHint": "body1",
            "weight": 2,
        },
        {
            "id": sc2,
            "component": "MaterialText",
            "text": slot["modality"],
            "usageHint": "body2",
            "weight": 2,
        },
        {
            "id": sbtn,
            "component": "MaterialButton",
            "label": "Book Slot",
            "appearance": "tonal",
            "loadingOnClick": True,
            "disabled": {"path": "/disabled"},
            "action": {
                "event": {
                    "name": "confirm_appointment",
                    "context": {
                        "surface_id": surface_id,
                        "surfaceId": surface_id,
                        "memberId": member_id,
                        "selectedSlotId": slot["slot_id"],
                        "slotTime": slot["time"],
                        "modality": slot["modality"],
                        "estimatedCopay": slot["copay"],
                        "prompt": (
                            f"Confirm appointment slot {slot['slot_id']}"
                            f" ({slot['time']})"
                        ),
                    },
                }
            },
        },
    ])

  # Primary Footer Action Bar
  footer_div = f"{prefix}_footer_div"
  footer_row = f"{prefix}_footer_row"
  confirm_btn = f"{prefix}_confirm_primary_btn"
  card_children.extend([footer_div, footer_row])
  components.extend([
      {"id": footer_div, "component": "MaterialDivider"},
      {
          "id": footer_row,
          "component": "MaterialRow",
          "justify": "end",
          "align": "center",
          "style": {"gap": "8px"},
          "children": [confirm_btn],
      },
      {
          "id": confirm_btn,
          "component": "MaterialButton",
          "label": "Confirm Priority Slot (Tomorrow 09:30 AM)",
          "appearance": "filled",
          "loadingOnClick": True,
          "disabled": {"path": "/disabled"},
          "action": {
              "event": {
                  "name": "confirm_appointment",
                  "context": {
                      "surface_id": surface_id,
                      "surfaceId": surface_id,
                      "memberId": member_id,
                      "selectedSlotId": "SLOT-TUE-0930",
                      "slotTime": "Tomorrow 09:30 AM",
                      "modality": "In-Person Cardiology Clinic",
                      "estimatedCopay": copay,
                      "prompt": (
                          "Confirm Priority Slot SLOT-TUE-0930 (Tomorrow"
                          " 09:30 AM)"
                      ),
                  },
              }
          },
      },
  ])

  all_components = [
      {
          "id": "root",
          "component": "MaterialCard",
          "appearance": "outlined",
          "style": {"marginBottom": "16px"},
          "children": card_children,
      },
      *components,
  ]
  return [
      {
          "version": "v0.9",
          "createSurface": {
              "surfaceId": surface_id,
              "catalogId": GEMINI_ENTERPRISE_CATALOG_ID,
              "sendDataModel": True,
          },
      },
      {
          "version": "v0.9",
          "updateComponents": {
              "surfaceId": surface_id,
              "components": all_components,
          },
      },
      {
          "version": "v0.9",
          "updateDataModel": {
              "surfaceId": surface_id,
              "path": "/",
              "value": {
                  "disabled": False,
                  "memberId": member_id,
                  "facilityId": facility_id,
                  "planTier": plan_tier,
                  "estimatedCopay": copay,
                  "selectedSlotId": "SLOT-TUE-0930",
                  "bookingStatus": "PENDING_SELECTION",
              },
          },
      },
  ]


def build_ge_booking_confirmed_summary_card(
    confirmation_code: str,
    slot_id: str,
    member_id: str,
    routed_owner: str,
    copay: str = "$25.00",
    slot_time: str = "Tomorrow 09:30 AM",
    facility_name: str = "Central Heart & Vascular Center (FACILITY-CENTRAL-01)",
) -> list[dict[str, Any]]:
  """Pattern 4: Builds a Gemini Enterprise Post-Booking Summary `MaterialCard` emitted in <5ms with 0 LLM tokens."""
  safe_suffix = re.sub(r"[^a-zA-Z0-9_]", "_", confirmation_code.lower())
  surface_id = f"booking_confirmed_{safe_suffix}_surface"
  prefix = f"confirmed_{safe_suffix}"

  rows = [
      ("Confirmation Code", confirmation_code),
      ("Booking Status", "CONFIRMED (Locked In)"),
      ("Selected Slot", f"{slot_id} • {slot_time}"),
      ("Care Center", facility_name),
      ("Member ID", member_id),
      ("Estimated Copay", copay),
      ("Routed Surface Owner (A2uiSubagentMap)", routed_owner),
      ("Execution Latency & Cost", "before_model_callback (<5ms, 0 LLM Tokens)"),
  ]

  components: list[dict[str, Any]] = [
      {
          "id": f"{prefix}_header_row",
          "component": "MaterialRow",
          "justify": "spaceBetween",
          "align": "center",
          "style": {"gap": "8px"},
          "children": [f"{prefix}_title", f"{prefix}_badge"],
      },
      {
          "id": f"{prefix}_title",
          "component": "MaterialText",
          "text": "Priority Cardiology Appointment Confirmed",
          "usageHint": "h5",
      },
      {
          "id": f"{prefix}_badge",
          "component": "MaterialText",
          "text": "CONFIRMED",
          "usageHint": "caption",
      },
      {
          "id": f"{prefix}_subtitle",
          "component": "MaterialText",
          "text": (
              "Pattern 4 Zero-LLM Action Short-Circuit • Processed"
              " deterministically in before_model_callback."
          ),
          "usageHint": "body2",
      },
      {"id": f"{prefix}_header_div", "component": "MaterialDivider"},
  ]
  card_children = [
      f"{prefix}_header_row",
      f"{prefix}_subtitle",
      f"{prefix}_header_div",
  ]

  for idx, (label, val) in enumerate(rows):
    if idx > 0:
      div_id = f"{prefix}_div_{idx}"
      card_children.append(div_id)
      components.append({"id": div_id, "component": "MaterialDivider"})
    row_id = f"{prefix}_row_{idx}"
    k_id = f"{prefix}_k_{idx}"
    v_id = f"{prefix}_v_{idx}"
    card_children.append(row_id)
    components.extend([
        {
            "id": row_id,
            "component": "MaterialRow",
            "justify": "spaceBetween",
            "align": "start",
            "style": {"gap": "16px"},
            "children": [k_id, v_id],
        },
        {
            "id": k_id,
            "component": "MaterialText",
            "text": label,
            "usageHint": "body2",
            "weight": 1,
        },
        {
            "id": v_id,
            "component": "MaterialText",
            "text": val,
            "usageHint": "body1",
            "weight": 2,
        },
    ])

  all_components = [
      {
          "id": "root",
          "component": "MaterialCard",
          "appearance": "outlined",
          "style": {"marginBottom": "16px"},
          "children": card_children,
      },
      *components,
  ]
  return [
      {
          "version": "v0.9",
          "createSurface": {
              "surfaceId": surface_id,
              "catalogId": GEMINI_ENTERPRISE_CATALOG_ID,
          },
      },
      {
          "version": "v0.9",
          "updateComponents": {
              "surfaceId": surface_id,
              "components": all_components,
          },
      },
  ]


# ============================================================================
# INBOUND ACTION EXTRACTION & BEFORE/AFTER MODEL CALLBACKS
# ============================================================================


def _extract_inbound_a2ui_action(part: types.Part) -> dict[str, Any] | None:
  """Extracts an A2UI button click action from either `inline_data` or `text`."""
  candidate_strings: list[str] = []
  if part.inline_data and part.inline_data.data:
    raw_bytes = part.inline_data.data
    if isinstance(raw_bytes, bytes):
      try:
        candidate_strings.append(raw_bytes.decode("utf-8"))
      except UnicodeDecodeError:
        pass
    elif isinstance(raw_bytes, str):
      candidate_strings.append(raw_bytes)
  if part.text:
    candidate_strings.append(part.text)

  for raw in candidate_strings:
    text = raw.strip()
    if not text:
      continue
    if text.startswith(A2A_DATA_PART_START_TAG) and text.endswith(
        A2A_DATA_PART_END_TAG
    ):
      text = text[
          len(A2A_DATA_PART_START_TAG) : -len(A2A_DATA_PART_END_TAG)
      ].strip()

    # Check formatted string: `User Selected Action: confirm_appointment with Context: {...}`
    m = _USER_ACTION_TEXT_PATTERN.search(text)
    if m:
      action_name = m.group(1)
      ctx_raw = m.group(2).strip()
      try:
        ctx_obj, _ = json.JSONDecoder().raw_decode(ctx_raw)
      except Exception:
        ctx_obj = {}
      surface_id = (
          ctx_obj.get("surface_id")
          or ctx_obj.get("surfaceId")
          or "slot_picker_surface_02"
      )
      return {
          "version": "v0.9",
          "action": {
              "name": action_name,
              "surfaceId": surface_id,
              "context": ctx_obj if isinstance(ctx_obj, dict) else {},
          },
      }

    # Check JSON object
    if "{" in text and "}" in text:
      start = text.find("{")
      end = text.rfind("}")
      try:
        parsed = json.loads(text[start : end + 1])
      except Exception:
        continue
      if not isinstance(parsed, Mapping):
        continue
      if isinstance(parsed.get("data"), Mapping):
        parsed = parsed["data"]
      for key in ("action", "userAction", "a2uiAction"):
        act = parsed.get(key)
        if isinstance(act, Mapping):
          name = act.get("name") or act.get("actionId") or act.get("action")
          if isinstance(name, str) and name:
            ctx = act.get("context") or act.get("args") or {}
            if not isinstance(ctx, dict):
              ctx = {}
            surface_id = (
                act.get("surfaceId")
                or parsed.get("surfaceId")
                or ctx.get("surface_id")
                or ctx.get("surfaceId")
                or "slot_picker_surface_02"
            )
            return {
                "version": "v0.9",
                "action": {
                    "name": name,
                    "surfaceId": surface_id,
                    "context": ctx,
                },
            }
      if isinstance(parsed.get("action"), str) and parsed.get("action"):
        ctx = parsed.get("context") or {}
        if not isinstance(ctx, dict):
          ctx = {}
        surface_id = (
            parsed.get("surfaceId")
            or ctx.get("surface_id")
            or ctx.get("surfaceId")
            or "slot_picker_surface_02"
        )
        return {
            "version": "v0.9",
            "action": {
                "name": parsed["action"],
                "surfaceId": surface_id,
                "context": ctx,
            },
        }
  return None


def _seed_default_playground_state(state: Any) -> None:
  """Seeds default member context in Agent Engine & Gemini Enterprise if not yet set."""
  defaults = {
      "member_id": "MEM-99412",
      "facility_id": "FACILITY-CENTRAL-01",
      "plan_tier": "PREMIER_EPO",
      "clinical_flags": "History of hypertension; active cardiac watch",
      "a2ui_client_capabilities": {
          "supportedCatalogIds": [
              GEMINI_ENTERPRISE_CATALOG_ID,
              CARE_PORTAL_CATALOG_ID,
          ]
      },
      "a2ui_surface_id_triage_intake_surface_01": "triage_specialist_agent",
      "a2ui_surface_id_slot_picker_surface_02": "scheduling_specialist_agent",
      "a2ui_surface_id_clinic_comparison_surface": "concierge_root",
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
  for k, v in defaults.items():
    if state.get(k) is None:
      state[k] = v


def playground_before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
  """Sanitizes historical A2UI blobs & executes Pattern 4 Zero-LLM Action Short-Circuiting."""
  _seed_default_playground_state(callback_context.state)

  if not llm_request.contents:
    return None

  # 1. Check if the latest user turn is an A2UI button click action (Pattern 4)
  last_content = llm_request.contents[-1]
  if last_content.role == "user" and last_content.parts:
    for part in last_content.parts:
      action_envelope = _extract_inbound_a2ui_action(part)
      if not action_envelope:
        continue
      action_obj = action_envelope["action"]
      action_name = str(action_obj.get("name", ""))
      if action_name in ("confirm_appointment", "select_slot"):
        surface_id = str(
            action_obj.get("surfaceId") or "slot_picker_surface_02"
        )
        ctx = action_obj.get("context") or {}
        slot_id = str(ctx.get("selectedSlotId") or "SLOT-TUE-0930")
        slot_time = str(ctx.get("slotTime") or "Tomorrow 09:30 AM")
        facility_name = str(
            ctx.get("facilityName")
            or "Central Heart & Vascular Center (FACILITY-CENTRAL-01)"
        )
        copay = str(ctx.get("estimatedCopay") or "$25.00")
        member_id = str(
            ctx.get("memberId")
            or callback_context.state.get("member_id", "MEM-99412")
        )

        # Pattern 5 deterministic surface owner lookup via `A2uiSubagentMap`
        routed_owner = (
            A2uiSubagentMap.get_subagent_name_for_action(
                action_envelope=action_envelope,
                session_state=callback_context.state,
            )
            or "scheduling_specialist_agent"
        )
        confirmation_code = f"CONF-{member_id[-4:]}-{slot_id[-4:]}"

        callback_context.state["last_routed_action_owner"] = routed_owner
        callback_context.state["last_confirmed_booking"] = {
            "confirmationCode": confirmation_code,
            "slotId": slot_id,
            "surfaceId": surface_id,
            "routedToSpecialist": routed_owner,
            "shortCircuitedVia": "before_model_callback (0 LLM tokens)",
        }

        lock_msg = build_surface_lock_message(
            surface_id=surface_id,
            selected_id=slot_id,
        )
        summary_card_msgs = build_ge_booking_confirmed_summary_card(
            confirmation_code=confirmation_code,
            slot_id=slot_id,
            member_id=member_id,
            routed_owner=routed_owner,
            copay=copay,
            slot_time=slot_time,
            facility_name=facility_name,
        )
        combined_envelopes = [lock_msg, *summary_card_msgs]
        callback_context.state["last_emitted_a2ui_envelopes"] = (
            combined_envelopes
        )

        response_text = (
            f"Appointment confirmed (`{confirmation_code}`) for slot"
            f" **{slot_id}** ({slot_time}) via deterministic"
            " `before_model_callback` short-circuit (**0 LLM tokens invoked**,"
            f" routed via `A2uiSubagentMap` to `{routed_owner}`)."
        )
        inline_parts = create_a2ui_inline_parts(combined_envelopes)
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=response_text), *inline_parts],
            ),
            custom_metadata={"a2a:response": True},
        )

  # 2. Sanitize historical `<a2a_datapart_json>` inline_data blobs from prior turns
  # so Vertex AI `gemini-2.5-flash` never rejects multi-turn conversation history.
  for content in llm_request.contents:
    if not content.parts:
      continue
    sanitized_parts: list[types.Part] = []
    for part in content.parts:
      if part.inline_data and part.inline_data.data:
        raw_bytes = part.inline_data.data
        data_str = (
            raw_bytes.decode("utf-8", errors="ignore")
            if isinstance(raw_bytes, bytes)
            else str(raw_bytes)
        )
        if A2A_DATA_PART_START_TAG in data_str or A2UI_MIME_TYPE in (
            part.inline_data.mime_type or ""
        ):
          continue
      if part.text and A2A_DATA_PART_START_TAG in part.text:
        cleaned = _A2A_DATA_PART_STRIP_REGEX.sub("", part.text).strip()
        if cleaned:
          sanitized_parts.append(types.Part.from_text(text=cleaned))
        continue
      sanitized_parts.append(part)
    if not sanitized_parts:
      sanitized_parts.append(
          types.Part.from_text(text="[Interactive A2UI card rendered]")
      )
    content.parts = sanitized_parts

  return None


def after_model_a2ui_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
  """Attaches staged A2UI v0.9 envelopes as `<a2a_datapart_json>` inline_data parts for Gemini Enterprise."""
  if (
      not llm_response
      or llm_response.partial
      or not llm_response.content
      or not llm_response.content.parts
  ):
    return llm_response

  # Do not modify intermediate function_call turns
  if any(part.function_call for part in llm_response.content.parts):
    return llm_response

  staged_envelopes = callback_context.state.get(STAGED_A2UI_KEY)
  if not staged_envelopes:
    return llm_response

  # Clear staged queue after popping
  callback_context.state[STAGED_A2UI_KEY] = []
  inline_parts = create_a2ui_inline_parts(staged_envelopes)
  if not inline_parts:
    return llm_response

  text_parts: list[types.Part] = []
  for part in llm_response.content.parts:
    if part.text and not part.thought:
      cleaned = _A2A_DATA_PART_STRIP_REGEX.sub("", part.text).strip()
      if cleaned:
        text_parts.append(types.Part.from_text(text=cleaned))
    else:
      text_parts.append(part)

  if not any(p.text and not p.thought for p in text_parts):
    text_parts.insert(
        0,
        types.Part.from_text(
            text="Here is the interactive Care Concierge A2UI card below:"
        ),
    )

  custom_metadata = dict(llm_response.custom_metadata or {})
  custom_metadata["a2a:response"] = True
  return llm_response.model_copy(
      update={
          "content": types.Content(
              role=llm_response.content.role or "model",
              parts=[*text_parts, *inline_parts],
          ),
          "custom_metadata": custom_metadata,
      }
  )


# ============================================================================
# ROOT AGENT TOOLS (Patterns 1, 2, 3, and 5)
# ============================================================================


def render_dynamic_wait_time_comparison(
    specialty: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 1: Stages an interactive Gemini Enterprise A2UI v0.9 Wait-Time Comparison Table Card (`clinic_comparison_surface`)."""
  _seed_default_playground_state(tool_context.state)
  member_id = tool_context.state.get("member_id", "MEM-99412")
  envelopes = build_ge_wait_time_comparison_card(
      specialty=specialty,
      member_id=member_id,
  )
  _stage_a2ui_envelopes(
      tool_context.state,
      envelopes,
      subagent_name="concierge_root",
  )
  return {
      "status": "SUCCESS",
      "surface_id": "clinic_comparison_surface",
      "catalog_id": GEMINI_ENTERPRISE_CATALOG_ID,
      "summary": (
          f"Staged interactive {specialty.title()} Wait-Time Comparison"
          " MaterialCard with 3 regional care centers. Reply with a brief 1-2"
          " sentence summary inviting the user to click 'Select Center' on any"
          " row."
      ),
  }


def render_appointment_slot_picker_ge(
    preferred_window: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 2: Stages a deterministic Gemini Enterprise A2UI v0.9 Appointment Slot Picker Card (`slot_picker_surface_02`)."""
  _seed_default_playground_state(tool_context.state)
  member_id = tool_context.state.get("member_id", "MEM-99412")
  facility_id = tool_context.state.get("facility_id", "FACILITY-CENTRAL-01")
  plan_tier = tool_context.state.get("plan_tier", "PREMIER_EPO")
  triage_output = tool_context.state.get(
      "triage_output", "Priority Cardiology Referral (PRIORITY_24H)"
  )
  envelopes = build_ge_slot_picker_card(
      preferred_window=preferred_window,
      member_id=member_id,
      facility_id=facility_id,
      plan_tier=plan_tier,
      triage_output=str(triage_output),
  )
  _stage_a2ui_envelopes(
      tool_context.state,
      envelopes,
      subagent_name="scheduling_specialist_agent",
  )
  return {
      "status": "SUCCESS",
      "surface_id": "slot_picker_surface_02",
      "catalog_id": GEMINI_ENTERPRISE_CATALOG_ID,
      "summary": (
          f"Staged interactive Priority Cardiology Slot Picker MaterialCard"
          f" for {member_id} ({preferred_window}). Reply with a brief 1-2"
          " sentence summary inviting the user to click 'Book Slot' or"
          " 'Confirm Priority Slot' on the card."
      ),
  }


def send_a2ui_json_to_client_ge(
    a2ui_json: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 3: Validates LLM-authored A2UI JSON via `parse_and_fix_a2ui_json` (self-healing retry on error) and stages the Gemini Enterprise `MaterialCard` Clinical Triage Intake surface (`triage_intake_surface_01`)."""
  _seed_default_playground_state(tool_context.state)
  try:
    validated_envelopes = parse_and_fix_a2ui_json(a2ui_json)
  except Exception as exc:  # pylint: disable=broad-except
    return {
        A2UI_ERROR_KEY: (
            f"Failed to validate A2UI v0.9 JSON: {exc}. Please fix the JSON"
            " and call `send_a2ui_json_to_client_ge` again."
        )
    }

  member_id = tool_context.state.get("member_id", "MEM-99412")
  facility_id = tool_context.state.get("facility_id", "FACILITY-CENTRAL-01")
  clinical_flags = tool_context.state.get(
      "clinical_flags", "History of hypertension; active cardiac watch"
  )
  ge_envelopes = build_ge_triage_intake_card(
      member_id=member_id,
      facility_id=facility_id,
      clinical_flags=clinical_flags,
  )
  _stage_a2ui_envelopes(
      tool_context.state,
      ge_envelopes,
      subagent_name="triage_specialist_agent",
  )
  return {
      "status": "VALIDATED_AND_STAGED",
      A2UI_VALIDATED_KEY: validated_envelopes,
      "surface_id": "triage_intake_surface_01",
      "catalog_id": GEMINI_ENTERPRISE_CATALOG_ID,
      "summary": (
          "Passed A2UI v0.9 schema & root-id validation and staged the"
          " Clinical Triage Intake MaterialCard (`triage_intake_surface_01`)."
          " Reply with a concise clinical triage summary."
      ),
  }


async def run_multiagent_a2a_triage_and_scheduling(
    symptom_description: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
  """Pattern 5: Runs Multi-Agent A2A orchestration across `triage_specialist_agent` and `scheduling_specialist_agent` with Single-Voice synthesis, `A2uiSubagentMap` surface ownership tracking, and cross-agent data model privacy stripping."""
  _seed_default_playground_state(tool_context.state)
  offline_mock = os.environ.get("A2UI_OFFLINE_MOCK", "0") == "1"

  triage_url = os.environ.get("REMOTE_TRIAGE_A2A_URL", "http://localhost:8011")
  sched_url = os.environ.get(
      "REMOTE_SCHEDULING_A2A_URL", "http://localhost:8012"
  )
  use_external_http = bool(
      os.environ.get("REMOTE_TRIAGE_A2A_URL")
      and os.environ.get("REMOTE_SCHEDULING_A2A_URL")
  )

  async with AsyncExitStack() as stack:
    if use_external_http:
      client_1 = await stack.enter_async_context(
          httpx.AsyncClient(timeout=60.0)
      )
      client_2 = await stack.enter_async_context(
          httpx.AsyncClient(timeout=60.0)
      )
    else:
      app_1 = create_remote_triage_a2ui_app(offline_mock=offline_mock)
      app_2 = create_remote_scheduling_a2ui_app(offline_mock=offline_mock)
      await stack.enter_async_context(app_1.router.lifespan_context(app_1))
      await stack.enter_async_context(app_2.router.lifespan_context(app_2))
      client_1 = await stack.enter_async_context(
          httpx.AsyncClient(
              transport=httpx.ASGITransport(app=app_1),
              base_url=triage_url,
              timeout=60.0,
          )
      )
      client_2 = await stack.enter_async_context(
          httpx.AsyncClient(
              transport=httpx.ASGITransport(app=app_2),
              base_url=sched_url,
              timeout=60.0,
          )
      )

    remote_triage = RemoteA2aAgent(
        name="triage_specialist_agent",
        description="Remote A2A Clinical Triage Specialist",
        agent_card=f"{triage_url}{AGENT_CARD_WELL_KNOWN_PATH}",
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
        description="Remote A2A Scheduling & Benefits Specialist",
        agent_card=f"{sched_url}{AGENT_CARD_WELL_KNOWN_PATH}",
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

    pipeline = SequentialAgent(
        name="multiagent_a2a_pipeline",
        sub_agents=[remote_triage, remote_scheduling],
    )
    sub_runner = InMemoryRunner(
        agent=pipeline, app_name="multiagent_a2a_subrunner"
    )
    seeded_state = dict(tool_context.state.to_dict())
    await sub_runner.session_service.create_session(
        app_name="multiagent_a2a_subrunner",
        user_id="playground_user",
        session_id="sess_a2a_bridge",
        state=seeded_state,
    )
    async for _ in sub_runner.run_async(
        user_id="playground_user",
        session_id="sess_a2a_bridge",
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=symptom_description)],
        ),
    ):
      pass

    completed_session = await sub_runner.session_service.get_session(
        app_name="multiagent_a2a_subrunner",
        user_id="playground_user",
        session_id="sess_a2a_bridge",
    )

    for k, v in completed_session.state.items():
      tool_context.state[k] = v

    filtered_for_scheduling, stripped_ids = (
        A2uiSubagentMap.strip_unowned_surfaces_from_data_model(
            target_subagent_name="scheduling_specialist_agent",
            client_data_model=tool_context.state.get(
                "a2ui_client_data_model", {}
            ),
            session_state=tool_context.state,
        )
    )
    tool_context.state["privacy_audit_log"] = {
        "originalClientDataModelSurfaces": list(
            tool_context.state.get("a2ui_client_data_model", {})
            .get("surfaces", {})
            .keys()
        ),
        "surfacesForwardedToSchedulingSpecialist": list(
            filtered_for_scheduling.get("surfaces", {}).keys()
        ),
        "strippedUnownedSurfaces": stripped_ids,
        "confidentialTriageSurfaceStripped": (
            "triage_intake_surface_01" in stripped_ids
        ),
    }

    member_id = tool_context.state.get("member_id", "MEM-99412")
    facility_id = tool_context.state.get("facility_id", "FACILITY-CENTRAL-01")
    plan_tier = tool_context.state.get("plan_tier", "PREMIER_EPO")
    clinical_flags = tool_context.state.get(
        "clinical_flags", "History of hypertension; active cardiac watch"
    )
    triage_card_envelopes = build_ge_triage_intake_card(
        member_id=member_id,
        facility_id=facility_id,
        clinical_flags=clinical_flags,
    )
    slot_card_envelopes = build_ge_slot_picker_card(
        preferred_window="Tomorrow Morning (Priority 24H)",
        member_id=member_id,
        facility_id=facility_id,
        plan_tier=plan_tier,
        triage_output="ACS-PATHWAY-01 • PRIORITY_24H Cardiology Referral",
    )
    _stage_a2ui_envelopes(
        tool_context.state,
        triage_card_envelopes,
        subagent_name="triage_specialist_agent",
    )
    _stage_a2ui_envelopes(
        tool_context.state,
        slot_card_envelopes,
        subagent_name="scheduling_specialist_agent",
    )

    return {
        "status": "SUCCESS",
        "single_voice_guidance": (
            "Synthesize a single, warm Care Concierge response for Member"
            f" {member_id} summarizing both `triage_output` and"
            " `scheduling_output`, and mention how `A2uiSubagentMap` stripped"
            " `triage_intake_surface_01` before calling"
            " `scheduling_specialist_agent`. Both interactive A2UI cards have"
            " been staged automatically."
        ),
        "triage_output": completed_session.state.get("triage_output"),
        "scheduling_output": completed_session.state.get("scheduling_output"),
        "surface_ownership_map": {
            "a2ui_surface_id_triage_intake_surface_01": (
                completed_session.state.get(
                    "a2ui_surface_id_triage_intake_surface_01"
                )
            ),
            "a2ui_surface_id_slot_picker_surface_02": (
                completed_session.state.get(
                    "a2ui_surface_id_slot_picker_surface_02"
                )
            ),
        },
        "privacy_audit_log": tool_context.state["privacy_audit_log"],
    }


_OFFLINE_MOCK = os.environ.get("A2UI_OFFLINE_MOCK", "0") == "1"

root_agent = LlmAgent(
    name="concierge_root",
    model=get_model("concierge_playground_root", offline_mock=_OFFLINE_MOCK),
    description=(
        "Single-Voice Care Concierge Root Orchestrator supporting all 5 A2UI"
        " v0.9 patterns in Gemini Enterprise (`MaterialCard` +"
        " `<a2a_datapart_json>`), Multi-Agent A2A surface ownership"
        " (`A2uiSubagentMap`), and cross-agent data model privacy."
    ),
    instruction=f"""You are `concierge_root`, the unified Single-Voice Care Concierge Orchestrator running on Vertex AI Agent Engine and Gemini Enterprise.
You always speak in one cohesive, empathetic voice while orchestrating interactive A2UI v0.9 `MaterialCard` UI surfaces.

Choose the right tool based on which A2UI pattern the user wants to test:
1. **Pattern 1 (Dynamic Wait-Time Comparison Table Card)**:
   - When the user asks to compare wait times across care centers/facilities, call `render_dynamic_wait_time_comparison`.
2. **Pattern 2 (Deterministic Appointment Slot Picker Card)**:
   - When the user asks to view or pick available appointment slots directly, call `render_appointment_slot_picker_ge`.
3. **Pattern 3 (Validated & Self-Healing Toolset)**:
   - When the user asks to generate or validate a `TriageIntakeCard` via the self-healing validator tool, call `send_a2ui_json_to_client_ge` with a valid A2UI v0.9 JSON array containing `createSurface`, `updateComponents` (with root component `"id": "root"` and `"component": "TriageIntakeCard"`), and `updateDataModel`.
4. **Pattern 4 (Zero-LLM Client Action Short-Circuiting)**:
   - Handled automatically in `<5ms` with 0 LLM tokens by `playground_before_model_callback` whenever the user clicks a button on any A2UI card (or sends a `confirm_appointment` action JSON)!
5. **Pattern 5 (Multi-Agent A2A Orchestration, Single Voice, Surface Ownership & Data Model Privacy)**:
   - When the user describes symptoms AND asks for both clinical triage and priority appointment scheduling across remote A2A specialists, call `run_multiagent_a2a_triage_and_scheduling`. Then present a warm, unified Care Concierge summary of `triage_output`, `scheduling_output`, and `privacy_audit_log`.

IMPORTANT: Never output raw JSON or `<a2ui-json>` code blocks in your text reply - `after_model_a2ui_callback` automatically attaches the staged A2UI v0.9 `MaterialCard` DataParts (`<a2a_datapart_json>`) to your response for Gemini Enterprise!

Strict A2UI v0.9 Schema Reference (for Pattern 3 tool argument):
{json.dumps(CARE_PORTAL_A2UI_SCHEMA)}
""",
    tools=[
        render_dynamic_wait_time_comparison,
        render_appointment_slot_picker_ge,
        send_a2ui_json_to_client_ge,
        run_multiagent_a2a_triage_and_scheduling,
    ],
    before_model_callback=playground_before_model_callback,
    after_model_callback=after_model_a2ui_callback,
)
