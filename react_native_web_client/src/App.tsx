/**
 * Demo shell: left = controls + wire logs, right = live A2UI surfaces rendered with React Native.
 *
 * Everything on the right-hand side is produced by @a2ui/web_core + the RN component registry;
 * nothing in this file knows about Cards, Buttons or profiles.
 */
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {MessageProcessor, type ActionPayload, type SurfaceModel} from '@a2ui/web_core/v0_9';
import type {ComponentApi} from '@a2ui/web_core/catalog';

import {ALL_CATALOGS, BASIC_CATALOG_ID, SOCIAL_CATALOG_ID} from './a2ui/catalog';
import {A2uiSurface} from './a2ui/A2uiRenderer';
import {registry} from './components/registry';
import {SCENARIOS, type A2uiMessage, composerComponents, composerData} from './scenarios';
import {mockAgentRespond} from './mockAgent';

interface LogEntry {
  t: string;
  dir: '→ agent' | '← agent' | '⚠ error';
  title: string;
  body: string;
}

export default function App() {
  const [surfaces, setSurfaces] = useState<SurfaceModel<ComponentApi>[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [streaming, setStreaming] = useState(true);
  const [paste, setPaste] = useState('');
  const [dataTick, setDataTick] = useState(0);
  const processorRef = useRef<MessageProcessor | null>(null);

  const addLog = useCallback((e: Omit<LogEntry, 't'>) => {
    setLog(prev => [{t: new Date().toLocaleTimeString(), ...e}, ...prev].slice(0, 60));
  }, []);

  // --- Create the MessageProcessor once. Catalogs decide what the agent may render. ---
  const processor = useMemo(() => {
    const p = new MessageProcessor(ALL_CATALOGS, undefined, {version: 'v0.9'});
    processorRef.current = p;
    return p;
  }, []);

  const apply = useCallback(
    (messages: A2uiMessage[], label = 'messages') => {
      try {
        processor.processMessages(messages as any);
        addLog({dir: '← agent', title: `${label} (${messages.length})`, body: JSON.stringify(messages, null, 1)});
        setDataTick(n => n + 1);
      } catch (err: any) {
        addLog({dir: '⚠ error', title: 'Rejected by MessageProcessor', body: String(err?.message ?? err)});
      }
    },
    [processor, addLog],
  );

  // --- Wire up: surfaces list + action round-trip to the (mock) agent ---
  useEffect(() => {
    const s1 = processor.onSurfaceCreated(() => setSurfaces([...processor.getSurfaces().values()]));
    const s2 = processor.onSurfaceDeleted(() => setSurfaces([...processor.getSurfaces().values()]));
    const s3 = processor.model.onAction.subscribe(async (action: ActionPayload) => {
      addLog({dir: '→ agent', title: `action "${action.name}" from ${action.sourceComponentId}`, body: JSON.stringify(action, null, 1)});
      const reply = await mockAgentRespond(action, (sid, path) => processor.getSurface(sid)?.dataModel.get(path));
      if (reply.length) apply(reply, `reply to "${action.name}"`);
    });
    return () => {
      s1.unsubscribe();
      s2.unsubscribe();
      s3.unsubscribe();
    };
  }, [processor, apply, addLog]);

  // Keep the data-model inspector fresh when any surface's data changes.
  useEffect(() => {
    const subs = surfaces.map(s => s.dataModel.subscribe('/', () => setDataTick(n => n + 1)));
    return () => subs.forEach(s => s.unsubscribe());
  }, [surfaces]);

  const runScenario = async (idx: number) => {
    const sc = SCENARIOS[idx];
    if (processor.getSurface(sc.surfaceId)) processor.model.deleteSurface(sc.surfaceId);
    if (!streaming) return apply(sc.messages, sc.title);
    // Streaming mode: deliver one message at a time, like SSE chunks arriving.
    for (const m of sc.messages) {
      apply([m], Object.keys(m).find(k => k !== 'version') ?? 'message');
      await new Promise(r => setTimeout(r, 450));
    }
  };

  // Smoke-test hook: open /?auto=1 to render every scenario (and ?click=Follow to tap a button).
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get('auto') !== '1') return;
    SCENARIOS.forEach(sc => apply(sc.messages, sc.title));
    const label = q.get('click');
    if (label) {
      setTimeout(() => {
        const el = [...document.querySelectorAll<HTMLElement>('[role="button"], [tabindex="0"]')].find(b => b.textContent?.trim() === label);
        el?.click();
      }, 800);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reset = () => {
    for (const id of [...processor.getSurfaces().keys()]) processor.model.deleteSurface(id);
    setLog([]);
  };

  const applyPasted = () => {
    try {
      const parsed = JSON.parse(paste);
      let msgs: A2uiMessage[];
      if (Array.isArray(parsed) && parsed.every(m => m && typeof m === 'object' && ('createSurface' in m || 'updateComponents' in m || 'updateDataModel' in m || 'deleteSurface' in m))) {
        msgs = parsed; // already A2UI messages
      } else if (parsed && Array.isArray(parsed.components)) {
        // Composer export shape: {components: [...], data: {...}}
        const sid = `pasted_${Date.now()}`;
        const usesCustom = parsed.components.some((c: any) => ['StatTile', 'ProfileHeader', 'ChipStrip'].includes(c.component));
        msgs = [
          {version: 'v0.9', createSurface: {surfaceId: sid, catalogId: usesCustom ? SOCIAL_CATALOG_ID : BASIC_CATALOG_ID}},
          {version: 'v0.9', updateComponents: {surfaceId: sid, components: parsed.components}},
          {version: 'v0.9', updateDataModel: {surfaceId: sid, path: '/', value: parsed.data ?? {}}},
        ];
      } else {
        throw new Error('Paste either an array of A2UI v0.9 messages or {components: [...], data: {...}} from the Composer.');
      }
      apply(msgs, 'pasted JSON');
    } catch (e: any) {
      addLog({dir: '⚠ error', title: 'Invalid JSON', body: String(e?.message ?? e)});
    }
  };

  return (
    <View style={st.app}>
      {/* Left column: controls and logs */}
      <ScrollView style={st.side} contentContainerStyle={{padding: 18, gap: 14}}>
        <Text style={st.brand}>A2UI + React Native Web</Text>
        <Text style={st.sub}>
          Renderer: <Text style={st.mono}>@a2ui/web_core</Text> for protocol, data binding and validation, plus React Native components
          (<Text style={st.mono}>View / Text / Image / Pressable</Text>) served by <Text style={st.mono}>react-native-web</Text>.
        </Text>

        <Section title="Scenarios">
          {SCENARIOS.map((sc, i) => (
            <Pressable key={sc.id} onPress={() => runScenario(i)} style={st.btn}>
              <Text style={st.btnTitle}>{sc.title}</Text>
              <Text style={st.btnSub}>{sc.subtitle}</Text>
            </Pressable>
          ))}
          <View style={{flexDirection: 'row', gap: 8, alignItems: 'center'}}>
            <Pressable onPress={() => setStreaming(s => !s)} style={[st.pill, streaming && st.pillOn]}>
              <Text style={[st.pillText, streaming && st.pillTextOn]}>{streaming ? 'Streaming: ON' : 'Streaming: OFF'}</Text>
            </Pressable>
            <Pressable onPress={reset} style={st.pill}>
              <Text style={st.pillText}>Reset all surfaces</Text>
            </Pressable>
            <Pressable
              onPress={() => setPaste(JSON.stringify({components: composerComponents, data: composerData}, null, 2))}
              style={st.pill}>
              <Text style={st.pillText}>Load Composer JSON</Text>
            </Pressable>
          </View>
        </Section>

        <Section title="Paste A2UI JSON (Composer export or v0.9 messages)">
          <TextInput
            multiline
            value={paste}
            onChangeText={setPaste}
            placeholder='{"components": [...], "data": {...}}  or  [{"version":"v0.9","createSurface":{...}}, ...]'
            placeholderTextColor="#64748b"
            style={st.textarea}
          />
          <Pressable onPress={applyPasted} style={[st.pill, st.pillOn, {alignSelf: 'flex-start'}]}>
            <Text style={st.pillTextOn}>Render pasted JSON</Text>
          </Pressable>
        </Section>

        <Section title="Catalogs registered with MessageProcessor">
          {ALL_CATALOGS.map(c => (
            <View key={c.id} style={st.catalogBox}>
              <Text style={st.mono}>{c.id}</Text>
              <Text style={st.sub}>
                {c.components.size} components · {c.functions.size} functions
                {c.id === SOCIAL_CATALOG_ID ? '  (+ StatTile, ProfileHeader, ChipStrip, initials)' : ''}
              </Text>
            </View>
          ))}
        </Section>

        <Section title={`Wire log (${log.length})`}>
          {log.map((e, i) => (
            <View key={i} style={[st.logRow, e.dir === '→ agent' && st.logOut, e.dir === '⚠ error' && st.logErr]}>
              <Text style={st.logHead}>
                {e.t}  {e.dir}  {e.title}
              </Text>
              <Text style={st.logBody} numberOfLines={12}>
                {e.body}
              </Text>
            </View>
          ))}
        </Section>
      </ScrollView>

      {/* Right column: rendered surfaces */}
      <ScrollView style={st.main} contentContainerStyle={{padding: 24, gap: 22}}>
        {surfaces.length === 0 ? (
          <View style={st.empty}>
            <Text style={st.emptyTitle}>No surfaces yet</Text>
            <Text style={st.sub}>Pick a scenario on the left. Each one is a stream of A2UI v0.9 messages.</Text>
          </View>
        ) : null}
        {surfaces.map(s => (
          <View key={s.id} style={st.surfaceWrap}>
            <View style={st.surfaceHead}>
              <Text style={st.surfaceTitle}>
                surface <Text style={st.mono}>{s.id}</Text>
              </Text>
              <Text style={st.sub}>
                catalog: <Text style={st.mono}>{s.defaultCatalog.id}</Text> · {s.componentsModel.size} components
              </Text>
            </View>
            <View style={st.phone}>
              <A2uiSurface surface={s} registry={registry} />
            </View>
            <DataModelInspector surface={s} tick={dataTick} />
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

function Section({title, children}: {title: string; children: React.ReactNode}) {
  return (
    <View style={{gap: 8}}>
      <Text style={st.h}>{title}</Text>
      {children}
    </View>
  );
}

function DataModelInspector({surface, tick}: {surface: SurfaceModel<ComponentApi>; tick: number}) {
  const json = useMemo(() => JSON.stringify(surface.dataModel.get('/') ?? {}, null, 1), [surface, tick]);
  return (
    <View style={st.dm}>
      <Text style={st.dmTitle}>live data model (reactive)</Text>
      <Text style={st.dmBody}>{json}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  app: {flex: 1, flexDirection: 'row', backgroundColor: '#0b1220'},
  side: {width: 440, borderRightWidth: 1, borderRightColor: '#1e293b', backgroundColor: '#0f172a'},
  main: {flex: 1},
  brand: {color: '#f8fafc', fontSize: 20, fontWeight: '800'},
  sub: {color: '#94a3b8', fontSize: 12.5, lineHeight: 18},
  mono: {fontFamily: 'monospace', color: '#7dd3fc', fontSize: 12},
  h: {color: '#e2e8f0', fontSize: 13, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.6},
  btn: {backgroundColor: '#1e293b', borderRadius: 12, padding: 12, gap: 2, borderWidth: 1, borderColor: '#334155'},
  btnTitle: {color: '#f1f5f9', fontWeight: '700'},
  btnSub: {color: '#94a3b8', fontSize: 12},
  pill: {paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: '#334155'},
  pillOn: {backgroundColor: '#2563eb', borderColor: '#2563eb'},
  pillText: {color: '#cbd5e1', fontSize: 12, fontWeight: '600'},
  pillTextOn: {color: '#fff', fontSize: 12, fontWeight: '700'},
  textarea: {minHeight: 110, backgroundColor: '#020617', color: '#e2e8f0', borderRadius: 10, padding: 10, fontFamily: 'monospace', fontSize: 11.5, borderWidth: 1, borderColor: '#334155'},
  catalogBox: {backgroundColor: '#020617', borderRadius: 10, padding: 10, gap: 2},
  logRow: {backgroundColor: '#020617', borderLeftWidth: 3, borderLeftColor: '#22c55e', borderRadius: 8, padding: 8, gap: 4},
  logOut: {borderLeftColor: '#f59e0b'},
  logErr: {borderLeftColor: '#ef4444'},
  logHead: {color: '#e2e8f0', fontSize: 11.5, fontWeight: '700'},
  logBody: {color: '#94a3b8', fontFamily: 'monospace', fontSize: 10.5},
  empty: {padding: 40, alignItems: 'center', gap: 6},
  emptyTitle: {color: '#e2e8f0', fontSize: 18, fontWeight: '700'},
  surfaceWrap: {gap: 10, alignItems: 'flex-start'},
  surfaceHead: {gap: 2},
  surfaceTitle: {color: '#f8fafc', fontWeight: '700'},
  phone: {width: 400, backgroundColor: '#f1f5f9', borderRadius: 28, padding: 14, borderWidth: 8, borderColor: '#1e293b'},
  dm: {width: 400, backgroundColor: '#020617', borderRadius: 12, padding: 10, gap: 4},
  dmTitle: {color: '#7dd3fc', fontSize: 11, fontWeight: '700', textTransform: 'uppercase'},
  dmBody: {color: '#94a3b8', fontFamily: 'monospace', fontSize: 10.5},
});
