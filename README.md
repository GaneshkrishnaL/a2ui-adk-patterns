# A2UI patterns with ADK, A2A and React Native

Reference code for building agent-driven UI with the A2UI protocol. It has two parts:

1. `concierge_a2ui_agent/` and `run_demo.py`: a Python ADK agent that shows five ways to produce A2UI
   from an agent, including a root agent that delegates to two remote A2A agents.
2. `react_native_web_client/`: a React Native renderer for A2UI v0.9 built on the official
   `@a2ui/web_core` package. It runs in the browser through react-native-web and the same component
   files run on iOS and Android.

Everything uses placeholder names (Care Concierge, example.org) so it can be adapted freely.

## The five agent-side patterns

| # | Pattern | Where to look |
| --- | --- | --- |
| 1 | Prompt-driven UI. The catalog schema is put in the LLM instruction and the model writes A2UI JSON inside `<a2ui-json>` tags. Shows list templates bound to a data path. | `remote_a2ui_agents.py` (`build_pattern1_dynamic_ui_agent`) |
| 2 | Tool-driven UI. A tool returns a pre-authored surface filled with live data and sets `skip_summarization = True`, so the LLM never rewrites the layout. Best for high-traffic cards. | `remote_a2ui_agents.py` (`render_appointment_slot_picker`) |
| 3 | Validated toolset. The model calls `send_a2ui_json_to_client`; the tool validates against the catalog schema and returns a structured error the model can fix on retry. | `remote_a2ui_agents.py`, `catalog_and_schema.py` |
| 4 | Client actions without an LLM call. A `before_model_callback` intercepts the button action, runs the business logic and returns an `updateDataModel` directly. | `agent.py`, `a2ui_orchestration_bridge.py` |
| 5 | Multi-agent A2A. A root agent keeps one voice while remote triage and scheduling agents produce surfaces. Surface ownership is tracked in session state and unrelated data is stripped before it crosses agent boundaries. | `agent.py` (`concierge_root`), `run_demo.py` |

`run_demo.py` runs all five in sequence and prints the A2A messages, the A2UI payloads and a span
summary for each turn.

## Running the agent demo

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Offline, deterministic. No credentials needed. Good first run.
python run_demo.py --offline-mock

# Same flow but with the two remote agents on real HTTP ports (8011, 8012).
./run_live_servers.sh

# Against Gemini on Vertex AI.
export GOOGLE_GENAI_USE_VERTEXAI=TRUE
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
python run_demo.py
```

To use the ADK developer UI instead of the script:

```bash
adk web --a2a .
```

and pick `concierge_a2ui_agent`.

## Deploying to Vertex AI Agent Engine

```bash
./deploy_to_agent_engine.sh your-project-id us-central1
```

The script passes `--otel_to_cloud`, so traces for every turn show up in Cloud Trace. Each
`call_llm` span carries `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`; group by
`trace_id` for a turn or by `gcp.vertex.agent.session_id` for a whole session.

## The React Native renderer

See `react_native_web_client/README.md`. Short version:

```bash
cd react_native_web_client
npm install
npm run dev      # http://localhost:8087
npm run smoke    # headless test that renders every scenario and taps a button
```

The client ships with three scenarios: the output of the A2UI Composer rendered on the standard
Basic Catalog, the same card rebuilt with custom catalog components, and a form that demonstrates
two-way data binding and client-side validation. A small in-browser mock stands in for the agent so
the action round trip can be seen without a backend. Swapping it for an Agent Engine or A2A client is
a few lines in `src/mockAgent.ts`.

## Useful links

- A2UI specification and docs: https://a2ui.org
- A2UI GitHub (spec, renderers, conformance suite, examples): https://github.com/google/A2UI
- A2UI Composer (design to JSON): https://a2ui-composer.ag-ui.com
- ADK docs: https://google.github.io/adk-docs/
- A2A protocol: https://a2a-protocol.org

## License

Apache 2.0. See the headers in each source file.
