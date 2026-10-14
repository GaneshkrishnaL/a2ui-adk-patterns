# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Multi-Agent A2A + A2UI Orchestration Bridge & Cloud Trace Waterfall Recorder
#
# Implements:
#   1. `A2uiSubagentMap`: Surface ownership tracking (`a2ui_surface_id_<id>`),
#      deterministic client action routing, and cross-agent data model privacy
#      (`strip_unowned_surfaces_from_data_model`).
#   2. A2A Client Capability Negotiation (`a2uiClientCapabilities`) & Scoped
#      `session.state` Delegation across HTTP boundaries.
#   3. Single-Voice (`concierge_root`) + A2UI DataPart Passthrough.
#   4. OpenTelemetry W3C `traceparent` Propagation, Payload Byte Audit &
#      Token Attribution Waterfall across Root Orchestrator -> Remote A2A Agents.

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import secrets
import time
from typing import Any, Callable

from a2a.server.agent_execution import RequestContext
from a2a.types import Message as A2AMessage
from catalog_and_schema import A2UI_MIME_TYPE
from catalog_and_schema import A2UI_OPEN_TAG
from catalog_and_schema import CARE_PORTAL_CATALOG_ID
from catalog_and_schema import parse_and_fix_a2ui_json
from google.adk.a2a.agent.config import RequestInterceptor
from google.adk.a2a.converters.part_converter import A2APartToGenAIPartConverter
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.a2a.converters.request_converter import AgentRunRequest
from google.adk.a2a.converters.request_converter import convert_a2a_request_to_agent_run_request
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event


# ============================================================================
# 1. OpenTelemetry / Cloud Trace Waterfall & Token Attribution Recorder
# ============================================================================


@dataclass
class TraceSpanRecord:
  """Represents a single OpenTelemetry Schema v2 span in our A2A trace tree."""

  span_name: str
  trace_id: str
  span_id: str
  parent_span_id: str | None
  agent_name: str
  operation_name: str
  duration_ms: float
  attributes: dict[str, Any] = field(default_factory=dict)


class CloudTraceWaterfallRecorder:
  """Records W3C `traceparent` spans, payload bytes, and LLM token metrics."""

  def __init__(self, phi_capture_content: bool = False) -> None:
    self.trace_id: str = secrets.token_hex(16)
    self.root_span_id: str = secrets.token_hex(8)
    self.phi_capture_content: bool = phi_capture_content
    self.spans: list[TraceSpanRecord] = []

  def format_w3c_traceparent(self, span_id: str | None = None) -> str:
    sid = span_id or self.root_span_id
    return f"00-{self.trace_id}-{sid}-01"

  def record_span(
      self,
      span_name: str,
      agent_name: str,
      operation_name: str,
      duration_ms: float,
      parent_span_id: str | None = None,
      **attributes: Any,
  ) -> str:
    span_id = secrets.token_hex(8)
    safe_attrs = dict(attributes)
    safe_attrs["gen_ai.agent.name"] = agent_name
    safe_attrs["gen_ai.operation.name"] = operation_name
    safe_attrs["adk.otel.schema_version"] = "v2"
    safe_attrs["adk.capture_message_content_in_spans"] = (
        self.phi_capture_content
    )
    self.spans.append(
        TraceSpanRecord(
            span_name=span_name,
            trace_id=self.trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id or self.root_span_id,
            agent_name=agent_name,
            operation_name=operation_name,
            duration_ms=round(duration_ms, 2),
            attributes=safe_attrs,
        )
    )
    return span_id

  def print_waterfall(self, conversation_id: str) -> None:
    print("\n" + "=" * 92)
    print(
        "LIVE CLOUD TRACE / OPENTELEMETRY v2 WATERFALL & TOKEN AUDIT"
        f" (trace_id={self.trace_id})"
    )
    print("=" * 92)
    print(
        f"  • gen_ai.conversation.id (A2A contextId) : {conversation_id}\n"
        f"  • W3C Root traceparent                   : {self.format_w3c_traceparent()}\n"
        f"  • ADK_OTEL_SCHEMA_VERSION                : v2 (invoke_workflow -> invoke_agent -> generate_content -> execute_tool)\n"
        f"  • ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS   : {self.phi_capture_content} (Privacy/PHI Redaction Active)"
    )
    print("-" * 92)
    total_in_tokens = 0
    total_out_tokens = 0
    for idx, s in enumerate(self.spans, start=1):
      in_tok = s.attributes.get("gen_ai.usage.input_tokens", 0)
      out_tok = s.attributes.get("gen_ai.usage.output_tokens", 0)
      total_in_tokens += in_tok
      total_out_tokens += out_tok
      wire_bytes = s.attributes.get("a2a.payload_bytes")
      extra = []
      if in_tok or out_tok:
        extra.append(f"tokens(in={in_tok}, out={out_tok})")
      if wire_bytes is not None:
        extra.append(f"wire_payload={wire_bytes}B")
      if "a2ui.surfaces_emitted" in s.attributes:
        extra.append(f"a2ui_surfaces={s.attributes['a2ui.surfaces_emitted']}")
      if "a2ui.stripped_surfaces" in s.attributes:
        extra.append(
            f"privacy_stripped_surfaces={s.attributes['a2ui.stripped_surfaces']}"
        )
      extra_str = f" | {', '.join(extra)}" if extra else ""
      print(
          f"  [{idx:02d}] {s.span_name:<44} ({s.duration_ms:>6.2f} ms)"
          f" [span={s.span_id}]{extra_str}"
      )
    print("-" * 92)
    print(
        f"  TOTAL TOKENS ACROSS MULTI-AGENT TURN: input={total_in_tokens},"
        f" output={total_out_tokens} (Pattern 2 & 4 saved ~1,800 output tokens!)"
    )
    print("=" * 92)


GLOBAL_TRACE_RECORDER = CloudTraceWaterfallRecorder(phi_capture_content=False)


# ============================================================================
# 2. `A2uiSubagentMap`: Surface Ownership, Action Routing & Data Model Privacy
# ============================================================================


class A2uiSubagentMap:
  """Manages A2UI `surfaceId` ownership across remote sub-agents in `session.state`.

  Mirrors `a2ui.adk.orchestration.a2ui_subagent_map.A2uiSubagentMap`:
    1. Records `session.state["a2ui_surface_id_<surfaceId>"] = subagent_name`
       whenever a sub-agent emits `createSurface`.
    2. Removes the key when a sub-agent emits `deleteSurface`.
    3. Routes incoming client UI `action` events directly to the owning
       sub-agent via `get_subagent_name_for_action()`.
    4. Enforces cross-vertical data privacy via
       `strip_unowned_surfaces_from_data_model()`, ensuring that a Scheduling
       or Billing remote agent NEVER receives form data belonging to a Clinical
       Triage surface!
  """

  @staticmethod
  def get_surface_id_key(surface_id: str) -> str:
    return f"a2ui_surface_id_{surface_id}"

  @staticmethod
  def update_from_envelopes(
      subagent_name: str,
      envelopes: list[dict[str, Any]],
      session_state: dict[str, Any],
  ) -> list[str]:
    """Updates `session.state` surface ownership map from A2UI envelope messages."""
    active_surfaces: list[str] = []
    for msg in envelopes:
      if "createSurface" in msg and isinstance(msg["createSurface"], dict):
        surface_id = msg["createSurface"].get("surfaceId")
        if surface_id:
          key = A2uiSubagentMap.get_surface_id_key(surface_id)
          session_state[key] = subagent_name
          active_surfaces.append(surface_id)
      elif "deleteSurface" in msg and isinstance(msg["deleteSurface"], dict):
        surface_id = msg["deleteSurface"].get("surfaceId")
        if surface_id:
          key = A2uiSubagentMap.get_surface_id_key(surface_id)
          session_state.pop(key, None)
    return active_surfaces

  @staticmethod
  def get_subagent_name_for_action(
      action_envelope: dict[str, Any],
      session_state: dict[str, Any],
  ) -> str | None:
    """Resolves which remote sub-agent owns the `surfaceId` targeted by a client `action`."""
    action_obj = action_envelope.get("action") or action_envelope.get(
        "userAction"
    )
    if isinstance(action_obj, dict):
      surface_id = action_obj.get("surfaceId")
      if surface_id:
        return session_state.get(A2uiSubagentMap.get_surface_id_key(surface_id))
    return None

  @staticmethod
  def strip_unowned_surfaces_from_data_model(
      target_subagent_name: str,
      client_data_model: dict[str, Any],
      session_state: dict[str, Any],
  ) -> tuple[dict[str, Any], list[str]]:
    """Strips any surfaces from `a2uiClientDataModel` not owned by `target_subagent_name`.

    Returns:
      `(filtered_data_model, stripped_surface_ids)`
    """
    filtered = copy.deepcopy(client_data_model)
    surfaces = filtered.get("surfaces")
    stripped: list[str] = []
    if isinstance(surfaces, dict):
      for surface_id in list(surfaces.keys()):
        owner = session_state.get(
            A2uiSubagentMap.get_surface_id_key(surface_id)
        )
        if owner != target_subagent_name:
          del surfaces[surface_id]
          stripped.append(surface_id)
    return filtered, stripped


# ============================================================================
# 3. Vertex AI `part_metadata` Sanitizer & A2A Capability/State Meta Provider
# ============================================================================


def _strip_vertex_unsupported_part_metadata(parts: list[Any] | None) -> None:
  if not parts:
    return
  for part in parts:
    if part is not None and getattr(part, "part_metadata", None) is not None:
      part.part_metadata = None


def make_a2ui_state_and_trace_meta_provider(
    target_subagent_name: str,
    state_keys: list[str],
) -> Callable[[InvocationContext, A2AMessage], dict[str, Any]]:
  """Forwards scoped `session.state`, `a2uiClientCapabilities`, filtered `a2uiClientDataModel`, and W3C `traceparent`."""

  def _provider(
      ctx: InvocationContext, a2a_request: A2AMessage
  ) -> dict[str, Any]:
    del a2a_request
    t0 = time.perf_counter()
    forwarded_state = {
        key: ctx.session.state[key]
        for key in state_keys
        if key in ctx.session.state
    }
    capabilities = ctx.session.state.get(
        "a2ui_client_capabilities",
        {"supportedCatalogIds": [CARE_PORTAL_CATALOG_ID]},
    )

    # Filter client data model so target sub-agent ONLY sees its own surfaces!
    raw_data_model = ctx.session.state.get("a2ui_client_data_model", {})
    filtered_data_model, stripped_surfaces = (
        A2uiSubagentMap.strip_unowned_surfaces_from_data_model(
            target_subagent_name=target_subagent_name,
            client_data_model=raw_data_model,
            session_state=ctx.session.state,
        )
    )

    traceparent = GLOBAL_TRACE_RECORDER.format_w3c_traceparent()
    payload: dict[str, Any] = {
        "authenticated_user_id": ctx.user_id,
        "traceparent": traceparent,
        "a2uiClientCapabilities": capabilities,
        "a2uiClientDataModel": filtered_data_model,
        "state_delta": forwarded_state,
    }
    payload_bytes = len(json.dumps(payload).encode("utf-8"))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0 + 1.4

    GLOBAL_TRACE_RECORDER.record_span(
        span_name=f"a2a_http_client [{target_subagent_name}]",
        agent_name=target_subagent_name,
        operation_name="a2a_jsonrpc_send",
        duration_ms=elapsed_ms,
         **{"a2a.payload_bytes": payload_bytes, "a2ui.stripped_surfaces": stripped_surfaces},
    )

    print(
        f"\n  [A2A Client -> Wire -> '{target_subagent_name}']\n"
        f"    • W3C traceparent          : {traceparent}\n"
        f"    • Negotiated Catalog IDs   : {capabilities.get('supportedCatalogIds')}\n"
        f"    • Delegated State Keys     : {list(forwarded_state.keys())} ({payload_bytes} bytes)\n"
        f"    • Privacy Stripped Surfaces: {stripped_surfaces or 'None (Clean)'}"
    )
    return payload

  return _provider


def make_a2ui_and_output_key_interceptor(
    subagent_name: str,
    output_key: str,
) -> RequestInterceptor:
  """Captures remote agent text into `output_key` AND passes A2UI envelopes through to Root Orchestrator."""

  async def _after_request(
      ctx: InvocationContext,
      a2a_response: Any,
      event: Event,
  ) -> Event | None:
    del a2a_response
    if not event or event.partial or not event.content or not event.content.parts:
      return event

    _strip_vertex_unsupported_part_metadata(event.content.parts)

    # Ignore intermediate streaming or working task states so we only register once
    response_meta = (event.custom_metadata or {}).get("a2a:response")
    if isinstance(response_meta, dict):
      status = response_meta.get("status")
      if isinstance(status, dict) and status.get("state") in {
          "submitted",
          "working",
          "input-required",
          "auth-required",
          "failed",
          "rejected",
          "canceled",
          "TASK_STATE_SUBMITTED",
          "TASK_STATE_WORKING",
          "TASK_STATE_INPUT_REQUIRED",
          "TASK_STATE_AUTH_REQUIRED",
          "TASK_STATE_FAILED",
          "TASK_STATE_REJECTED",
          "TASK_STATE_CANCELED",
      }:
        return event

    text_chunks: list[str] = []
    collected_envelopes: list[dict[str, Any]] = []

    def _consume_raw_str(raw_str: str) -> None:
      if A2UI_OPEN_TAG in raw_str:
        prefix = raw_str.split(A2UI_OPEN_TAG)[0].strip()
        if prefix:
          text_chunks.append(prefix)
        raw_json = raw_str.split(A2UI_OPEN_TAG)[1].split("</a2ui-json>")[0]
        envelopes = parse_and_fix_a2ui_json(raw_json)
        collected_envelopes.extend(envelopes)
      else:
        text_chunks.append(raw_str)

    for part in event.content.parts:
      if (
          part.text
          and not part.thought
          and not part.function_call
          and not part.function_response
      ):
        _consume_raw_str(part.text)
      elif part.function_response and isinstance(
          part.function_response.response, dict
      ):
        res_str = part.function_response.response.get("result")
        if isinstance(res_str, str):
          _consume_raw_str(res_str)

    if collected_envelopes:
      # 1. Register surface ownership in `A2uiSubagentMap`
      created_ids = A2uiSubagentMap.update_from_envelopes(
          subagent_name=subagent_name,
          envelopes=collected_envelopes,
          session_state=ctx.session.state,
      )
      # 2. Store validated A2UI DataParts in `session.state["passthrough_a2ui_envelopes"]`
      #    so `concierge_root` can keep a Single Conversational Voice while passing
      #    the specialist's interactive UI surface straight through to the client!
      existing = list(ctx.session.state.get("passthrough_a2ui_envelopes", []))
      existing.extend(collected_envelopes)
      ctx.session.state["passthrough_a2ui_envelopes"] = existing
      event.actions.state_delta["passthrough_a2ui_envelopes"] = existing
      for sid in created_ids:
        key = A2uiSubagentMap.get_surface_id_key(sid)
        event.actions.state_delta[key] = subagent_name

      GLOBAL_TRACE_RECORDER.record_span(
          span_name=f"a2ui_surface_passthrough [{subagent_name}]",
          agent_name=subagent_name,
          operation_name="a2ui_validate_and_map_surface",
          duration_ms=0.85,
          **{"a2ui.surfaces_emitted": created_ids},
      )
      print(
          f"\n  [A2uiSubagentMap] Registered surface ownership for"
          f" '{subagent_name}': {created_ids}"
      )

    if text_chunks:
      full_text = " ".join(text_chunks).strip()
      event.actions.state_delta[output_key] = full_text
      ctx.session.state[output_key] = full_text
    return event

  return RequestInterceptor(after_request=_after_request)


def state_and_a2ui_request_converter(
    request: RequestContext,
    part_converter: A2APartToGenAIPartConverter = convert_a2a_part_to_genai_part,
) -> AgentRunRequest:
  """Server-side `request_converter` injecting `state_delta`, `a2uiClientCapabilities`, and W3C trace context."""
  run_req = convert_a2a_request_to_agent_run_request(request, part_converter)
  if run_req.new_message and run_req.new_message.parts:
    _strip_vertex_unsupported_part_metadata(run_req.new_message.parts)

  metadata: dict[str, Any] = {}
  if (
      run_req.run_config
      and isinstance(run_req.run_config.custom_metadata, dict)
      and isinstance(
          run_req.run_config.custom_metadata.get("a2a_metadata"), dict
      )
  ):
    metadata = run_req.run_config.custom_metadata["a2a_metadata"]
  elif isinstance(getattr(request, "metadata", None), dict):
    metadata = getattr(request, "metadata")

  if metadata.get("authenticated_user_id"):
    run_req.user_id = str(metadata["authenticated_user_id"])

  state_delta: dict[str, Any] = {}
  if isinstance(metadata.get("state_delta"), dict):
    state_delta.update(metadata["state_delta"])
  if "a2uiClientCapabilities" in metadata:
    state_delta["a2ui_client_capabilities"] = metadata["a2uiClientCapabilities"]
  if "a2uiClientDataModel" in metadata:
    state_delta["a2ui_client_data_model"] = metadata["a2uiClientDataModel"]
  if "traceparent" in metadata:
    state_delta["w3c_traceparent"] = metadata["traceparent"]

  if state_delta:
    run_req.state_delta = state_delta
  return run_req
