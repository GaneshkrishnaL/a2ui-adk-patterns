# A2UI renderer for React Native (web build)

An A2UI v0.9 renderer written against the official `@a2ui/web_core` engine. The UI layer is plain
React Native (`View`, `Text`, `Image`, `Pressable`, `TextInput`). In this folder it is served to a
browser through react-native-web with Vite; in an Expo or bare React Native app the same files run
on iOS and Android.

## How the pieces fit

```
agent (ADK / A2A / mock)
   |  A2UI v0.9 messages: createSurface, updateComponents, updateDataModel, deleteSurface
   v
@a2ui/web_core
   MessageProcessor  -> validates messages against the catalog, builds SurfaceModels
   DataModel         -> reactive store addressed by JSON Pointer paths
   GenericBinder     -> turns raw component JSON into resolved props
                        ({path} -> value, action -> function, checks -> isValid)
   |
   v
React Native components (src/components)          <- the only part you write
   |
   v
react-native-web in the browser, React Native on iOS and Android
```

## Run

```bash
npm install
npm run dev     # http://localhost:8087
npm run smoke   # headless jsdom test: renders all scenarios and taps the Follow button
npm run build   # type check + production bundle
```

## Files

| File | What it is |
| --- | --- |
| `src/a2ui/catalog.ts` | Two catalogs. The first is the standard Basic Catalog with its official id, so JSON from the A2UI Composer renders as is. The second extends it with three custom components (`StatTile`, `ProfileHeader`, `ChipStrip`) and a custom function (`initials`). Schemas are Zod; the `REF:#/$defs/...` descriptions tell web_core which props are data bindings, actions or child references. |
| `src/a2ui/A2uiRenderer.tsx` | The glue between web_core and React. About 120 lines. Creates a `ComponentContext` and `GenericBinder` per component, subscribes to prop changes, and recurses through children. Template children (`{componentId, path}`) get a data context scoped to their list item. |
| `src/components/basic.tsx` | React Native versions of the 18 Basic Catalog components. |
| `src/components/custom.tsx` | React Native versions of the three custom components. |
| `src/components/registry.ts` | Maps a component name to its implementation. Adding a widget is one line here plus the schema in `catalog.ts`. |
| `src/scenarios.ts` | Three message streams used by the demo UI (see below). |
| `src/mockAgent.ts` | Answers client actions with more A2UI messages so the round trip works without a server. Replace with your transport. |
| `src/App.tsx` | Demo shell: scenario buttons, streaming toggle, a box to paste any A2UI JSON, a wire log and a live view of each surface's data model. |
| `scripts/smoke.ts` | Headless test used by `npm run smoke`. |

## The scenarios

1. Composer output on the Basic Catalog. The JSON is exactly what the A2UI Composer produced for a
   profile card. Tap Follow: the renderer sends `{name: "follow"}` to the agent, the agent answers
   with two `updateDataModel` messages, and the label and follower count update in place.
2. Custom catalog. Same card built from `ProfileHeader`, `ChipStrip` and `StatTile`, a title that
   uses the custom `initials()` function inside `formatString`, and a `Column` whose children come
   from a template bound to `/recentPosts`. Tapping a tile or the Message button shows the agent
   updating data and creating a new surface.
3. Form. `TextField`, `ChoicePicker` and `CheckBox` write to the data model through two-way
   bindings. The Send button has `checks` and stays disabled until `required` and `length(min: 4)`
   pass.

With streaming on, messages are delivered one at a time so progressive rendering is visible.
Anything that is not in the catalog is rejected by `MessageProcessor` and appears in the wire log.

## Connecting a real agent

Replace `mockAgentRespond` in `src/mockAgent.ts`. For an agent on Vertex AI Agent Engine the shape is:

```ts
// outbound: send the ActionPayload as the user's turn
await fetch(`${AGENT_ENGINE_URL}:streamQuery?alt=sse`, {
  method: 'POST',
  headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
  body: JSON.stringify({
    class_method: 'async_stream_query',
    input: {user_id, session_id, message: {role: 'user', parts: [{text: JSON.stringify({a2uiAction: action})}]}},
  }),
});
// inbound: for each SSE event, collect the A2UI messages and hand them to the processor
processor.processMessages(messages);
```

## Using it on iOS and Android

`src/a2ui` and `src/components` are plain React Native. In an Expo project:

```bash
npx create-expo-app a2ui-mobile && cd a2ui-mobile
npm i @a2ui/web_core zod
cp -r ../react_native_web_client/src/a2ui ../react_native_web_client/src/components ./src/
```

Import only the subpaths used here (`@a2ui/web_core/catalog`, `@a2ui/web_core/v0_9`,
`@a2ui/web_core/v0_9/basic_catalog`). The package also contains Lit web components for browsers;
do not import `@a2ui/web_core/universal` in a native bundle.

## Notes

- `src/react-native.d.ts` declares the `react-native` module loosely because react-native-web does
  not ship types. In a real RN project delete that file and use the types from `react-native`.
- `formatString` takes one `value` argument written as a template, for example
  `"Hello ${/name}"` or `"${formatNumber(value: likes)}"`.
