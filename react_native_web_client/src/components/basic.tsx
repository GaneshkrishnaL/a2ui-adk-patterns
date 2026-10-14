/**
 * React Native implementations of the A2UI v0.9 Basic Catalog components.
 *
 * Everything here is plain `react-native` - `View`, `Text`, `Image`, `Pressable`, `TextInput`,
 * `Switch`, `ScrollView`. On the web these are served by `react-native-web`; in an Expo / RN
 * app the exact same file runs on iOS and Android.
 *
 * Props arrive ALREADY RESOLVED from @a2ui/web_core's GenericBinder:
 *   - `{path: "/name"}`            -> "Sarah Chen"
 *   - `{call: "formatNumber", …}`  -> "12,400"
 *   - `action: {event: {...}}`     -> () => Promise<void>   (dispatches to the agent)
 *   - `value: {path: "/x"}`        -> current value  +  `setValue(v)` two-way setter
 *   - `checks: [...]`              -> `isValid` / `validationErrors`
 */
import React, {useState} from 'react';
import {
  Image,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import type {A2uiComponentProps, ChildRef} from '../a2ui/A2uiRenderer';
import {theme} from './theme';

// ---------- helpers ----------
const justifyMap: Record<string, any> = {
  start: 'flex-start',
  end: 'flex-end',
  center: 'center',
  spaceAround: 'space-around',
  spaceBetween: 'space-between',
  spaceEvenly: 'space-evenly',
  stretch: 'stretch',
};
const alignMap: Record<string, any> = {
  start: 'flex-start',
  end: 'flex-end',
  center: 'center',
  stretch: 'stretch',
};

function renderChildren(children: ChildRef[] | undefined, renderChild: A2uiComponentProps['renderChild']) {
  if (!Array.isArray(children)) return null;
  return children.map((c, i) => (
    <React.Fragment key={typeof c === 'string' ? c : `${c.id}@${c.basePath}`}>{renderChild(c)}</React.Fragment>
  ));
}

/** Minimal inline-markdown: **bold**, *italic*, `code`. */
function renderInlineMarkdown(text: string, baseStyle: any) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean);
  return tokens.map((t, i) => {
    if (t.startsWith('**')) return <Text key={i} style={[baseStyle, {fontWeight: '700'}]}>{t.slice(2, -2)}</Text>;
    if (t.startsWith('`')) return <Text key={i} style={[baseStyle, styles.code]}>{t.slice(1, -1)}</Text>;
    if (t.startsWith('*')) return <Text key={i} style={[baseStyle, {fontStyle: 'italic'}]}>{t.slice(1, -1)}</Text>;
    return <Text key={i} style={baseStyle}>{t}</Text>;
  });
}

// ---------- Layout ----------
export const CardRN = ({props, renderChild}: A2uiComponentProps) => (
  <View style={[styles.card, props.weight ? {flex: props.weight} : null]}>{renderChild(props.child)}</View>
);

export const ColumnRN = ({props, renderChild}: A2uiComponentProps) => (
  <View
    style={[
      styles.column,
      {justifyContent: justifyMap[props.justify ?? 'start'], alignItems: alignMap[props.align ?? 'stretch']},
      props.weight ? {flex: props.weight} : null,
    ]}>
    {renderChildren(props.children, renderChild)}
  </View>
);

export const RowRN = ({props, renderChild}: A2uiComponentProps) => (
  <View
    style={[
      styles.row,
      {justifyContent: justifyMap[props.justify ?? 'start'], alignItems: alignMap[props.align ?? 'stretch']},
      props.weight ? {flex: props.weight} : null,
    ]}>
    {renderChildren(props.children, renderChild)}
  </View>
);

export const ListRN = ({props, renderChild}: A2uiComponentProps) => {
  const horizontal = props.direction === 'horizontal';
  return (
    <ScrollView horizontal={horizontal} style={styles.list} contentContainerStyle={horizontal ? styles.row : styles.column}>
      {renderChildren(props.children, renderChild)}
    </ScrollView>
  );
};

export const DividerRN = ({props}: A2uiComponentProps) => (
  <View style={props.axis === 'vertical' ? styles.dividerV : styles.dividerH} />
);

export const TabsRN = ({props, renderChild}: A2uiComponentProps) => {
  const [active, setActive] = useState(0);
  const items: {title: string; child: string}[] = props.tabItems ?? [];
  return (
    <View>
      <View style={styles.tabBar}>
        {items.map((t, i) => (
          <Pressable key={i} onPress={() => setActive(i)} style={[styles.tab, i === active && styles.tabActive]}>
            <Text style={[styles.tabText, i === active && styles.tabTextActive]}>{String(t.title)}</Text>
          </Pressable>
        ))}
      </View>
      {items[active] ? renderChild(items[active].child) : null}
    </View>
  );
};

export const ModalRN = ({props, renderChild}: A2uiComponentProps) => {
  const [open, setOpen] = useState(false);
  return (
    <View>
      <Pressable onPress={() => setOpen(true)}>{renderChild(props.trigger)}</Pressable>
      {open && (
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            {renderChild(props.content)}
            <Pressable onPress={() => setOpen(false)} style={[styles.button, styles.buttonDefault, {marginTop: 12}]}>
              <Text style={styles.buttonTextDefault}>Close</Text>
            </Pressable>
          </View>
        </View>
      )}
    </View>
  );
};

// ---------- Display ----------
export const TextRN = ({props}: A2uiComponentProps) => {
  const variant: string = props.variant ?? 'body';
  const style = (styles as any)[`text_${variant}`] ?? styles.text_body;
  const value = props.text === undefined || props.text === null ? '' : String(props.text);
  return <Text style={[style, props.weight ? {flex: props.weight} : null]}>{renderInlineMarkdown(value, style)}</Text>;
};

const imageSize: Record<string, number> = {
  icon: 24,
  avatar: 96,
  smallFeature: 120,
  mediumFeature: 200,
  largeFeature: 320,
  header: 360,
};
export const ImageRN = ({props}: A2uiComponentProps) => {
  const variant: string = props.variant ?? 'mediumFeature';
  const size = imageSize[variant] ?? 200;
  const isAvatar = variant === 'avatar';
  const fit = props.fit === 'contain' ? 'contain' : props.fit === 'fill' ? 'stretch' : 'cover';
  if (!props.url) return null;
  return (
    <Image
      accessibilityLabel={props.description ? String(props.description) : undefined}
      source={{uri: String(props.url)}}
      resizeMode={fit}
      style={[
        {width: variant === 'header' ? '100%' : size, height: size, borderRadius: isAvatar ? size / 2 : 12},
        isAvatar && {borderWidth: 3, borderColor: theme.accent},
      ]}
    />
  );
};

const ICONS: Record<string, string> = {
  check: '✓', close: '✕', add: '＋', remove: '－', star: '★', starHalf: '☆', favorite: '♥',
  search: '⌕', settings: '⚙', info: 'ℹ', warning: '⚠', error: '⨂', home: '⌂', menu: '☰',
  arrowBack: '←', arrowForward: '→', calendarToday: '📅', schedule: '🕒', locationOn: '📍',
  person: '👤', mail: '✉', phone: '☎', share: '⤴', edit: '✎', delete: '🗑', download: '⤓',
  upload: '⤒', refresh: '↻', visibility: '👁', lock: '🔒', verified: '✅',
};
export const IconRN = ({props}: A2uiComponentProps) => (
  <Text style={styles.icon}>{ICONS[String(props.name)] ?? '•'}</Text>
);

export const VideoRN = ({props}: A2uiComponentProps) => (
  <Pressable onPress={() => Linking.openURL(String(props.url))} style={styles.mediaBox}>
    <Text style={styles.mediaText}>▶ Video: {String(props.url)}</Text>
  </Pressable>
);
export const AudioPlayerRN = ({props}: A2uiComponentProps) => (
  <Pressable onPress={() => Linking.openURL(String(props.url))} style={styles.mediaBox}>
    <Text style={styles.mediaText}>🔊 {String(props.description ?? props.url)}</Text>
  </Pressable>
);

// ---------- Interactive ----------
export const ButtonRN = ({props, renderChild}: A2uiComponentProps) => {
  const variant: string = props.variant ?? 'default';
  const disabled = props.isValid === false || typeof props.action !== 'function';
  const [pressed, setPressed] = useState(false);
  return (
    <View style={props.weight ? {flex: props.weight} : null}>
      <Pressable
        role="button"
        accessibilityRole="button"
        disabled={disabled}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        onPress={() => props.action?.()}
        style={[
          styles.button,
          variant === 'primary' ? styles.buttonPrimary : variant === 'borderless' ? styles.buttonBorderless : styles.buttonDefault,
          disabled && styles.buttonDisabled,
          pressed && {opacity: 0.75},
        ]}>
        <View style={variant === 'primary' ? styles.buttonPrimaryInner : undefined}>{renderChild(props.child)}</View>
      </Pressable>
      {props.validationErrors?.length ? (
        <Text style={styles.error}>{props.validationErrors.join(' · ')}</Text>
      ) : null}
    </View>
  );
};

export const TextFieldRN = ({props}: A2uiComponentProps) => {
  const variant: string = props.variant ?? 'shortText';
  return (
    <View style={styles.field}>
      {props.label ? <Text style={styles.label}>{String(props.label)}</Text> : null}
      <TextInput
        value={props.value === undefined || props.value === null ? '' : String(props.value)}
        onChangeText={(t: string) => props.setValue?.(variant === 'number' ? Number(t) || t : t)}
        secureTextEntry={variant === 'obscured'}
        multiline={variant === 'longText'}
        keyboardType={variant === 'number' ? 'numeric' : 'default'}
        placeholder={props.label ? String(props.label) : undefined}
        placeholderTextColor="#94a3b8"
        style={[styles.input, variant === 'longText' && {minHeight: 80}, props.isValid === false && styles.inputInvalid]}
      />
      {props.validationErrors?.length ? <Text style={styles.error}>{props.validationErrors.join(' · ')}</Text> : null}
    </View>
  );
};

export const CheckBoxRN = ({props}: A2uiComponentProps) => (
  <View style={[styles.row, {alignItems: 'center', gap: 10}]}>
    <Switch value={Boolean(props.value)} onValueChange={(v: boolean) => props.setValue?.(v)} />
    <Text style={styles.text_body}>{String(props.label ?? '')}</Text>
  </View>
);

export const ChoicePickerRN = ({props}: A2uiComponentProps) => {
  const options: {label: string; value: string}[] = props.options ?? [];
  const selected: string[] = Array.isArray(props.value) ? props.value : [];
  const exclusive = props.variant !== 'multipleSelection';
  const toggle = (v: string) => {
    const next = selected.includes(v)
      ? selected.filter(s => s !== v)
      : exclusive
        ? [v]
        : [...selected, v];
    props.setValue?.(next);
  };
  return (
    <View style={styles.field}>
      {props.label ? <Text style={styles.label}>{String(props.label)}</Text> : null}
      <View style={[styles.row, {flexWrap: 'wrap', gap: 8}]}>
        {options.map(o => {
          const on = selected.includes(o.value);
          return (
            <Pressable key={o.value} onPress={() => toggle(o.value)} style={[styles.chip, on && styles.chipOn]}>
              <Text style={[styles.chipText, on && styles.chipTextOn]}>{String(o.label)}</Text>
            </Pressable>
          );
        })}
      </View>
      {props.validationErrors?.length ? <Text style={styles.error}>{props.validationErrors.join(' · ')}</Text> : null}
    </View>
  );
};

export const SliderRN = ({props}: A2uiComponentProps) => {
  const min = Number(props.min ?? 0);
  const max = Number(props.max ?? 100);
  const val = Number(props.value ?? min);
  const step = (max - min) / 10 || 1;
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{String(props.label ?? '')}: {val}</Text>
      <View style={[styles.row, {gap: 8, alignItems: 'center'}]}>
        <Pressable style={styles.stepBtn} onPress={() => props.setValue?.(Math.max(min, val - step))}><Text>−</Text></Pressable>
        <View style={styles.track}><View style={[styles.trackFill, {width: `${((val - min) / (max - min)) * 100}%`}]} /></View>
        <Pressable style={styles.stepBtn} onPress={() => props.setValue?.(Math.min(max, val + step))}><Text>＋</Text></Pressable>
      </View>
    </View>
  );
};

export const DateTimeInputRN = ({props}: A2uiComponentProps) => (
  <View style={styles.field}>
    {props.label ? <Text style={styles.label}>{String(props.label)}</Text> : null}
    <TextInput
      value={props.value ? String(props.value) : ''}
      onChangeText={(t: string) => props.setValue?.(t)}
      placeholder={props.enableTime === false ? 'YYYY-MM-DD' : 'YYYY-MM-DDTHH:MM'}
      placeholderTextColor="#94a3b8"
      style={styles.input}
    />
  </View>
);

export const UnknownRN = ({context}: A2uiComponentProps) => (
  <View style={styles.unknown}>
    <Text style={styles.error}>Unsupported component: {context.componentModel.type}</Text>
  </View>
);

// ---------- styles ----------
export const styles = StyleSheet.create({
  card: {
    backgroundColor: theme.surface, borderRadius: 18, padding: 20, borderWidth: 1, borderColor: theme.border,
    shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 14, shadowOffset: {width: 0, height: 6}, elevation: 4,
  },
  column: {flexDirection: 'column', gap: 10},
  row: {flexDirection: 'row', gap: 10},
  list: {maxHeight: 420},
  dividerH: {height: 1, backgroundColor: theme.border, marginVertical: 6, alignSelf: 'stretch'},
  dividerV: {width: 1, backgroundColor: theme.border, marginHorizontal: 6, alignSelf: 'stretch'},
  text_h1: {fontSize: 30, fontWeight: '800', color: theme.text},
  text_h2: {fontSize: 24, fontWeight: '700', color: theme.text},
  text_h3: {fontSize: 19, fontWeight: '700', color: theme.text},
  text_h4: {fontSize: 16, fontWeight: '700', color: theme.text},
  text_h5: {fontSize: 14, fontWeight: '700', color: theme.text},
  text_body: {fontSize: 15, color: theme.text, lineHeight: 22},
  text_caption: {fontSize: 12.5, color: theme.muted},
  code: {fontFamily: 'monospace', backgroundColor: '#eef2ff', paddingHorizontal: 4, borderRadius: 4},
  icon: {fontSize: 18, color: theme.accent},
  mediaBox: {backgroundColor: '#0f172a', borderRadius: 12, padding: 14},
  mediaText: {color: '#e2e8f0'},
  button: {borderRadius: 12, paddingVertical: 11, paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center'},
  buttonDefault: {backgroundColor: theme.accent},
  buttonPrimary: {backgroundColor: theme.accent},
  buttonPrimaryInner: {},
  buttonBorderless: {backgroundColor: 'transparent'},
  buttonDisabled: {backgroundColor: '#cbd5e1'},
  buttonTextDefault: {color: '#fff', fontWeight: '600'},
  field: {gap: 6},
  label: {fontSize: 12.5, fontWeight: '600', color: theme.muted},
  input: {borderWidth: 1, borderColor: theme.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9, fontSize: 15, color: theme.text, backgroundColor: '#fff'},
  inputInvalid: {borderColor: '#dc2626'},
  error: {color: '#dc2626', fontSize: 12},
  chip: {paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: theme.border, backgroundColor: '#fff'},
  chipOn: {backgroundColor: theme.accent, borderColor: theme.accent},
  chipText: {color: theme.text, fontSize: 13},
  chipTextOn: {color: '#fff', fontWeight: '600'},
  stepBtn: {width: 30, height: 30, borderRadius: 15, backgroundColor: '#e2e8f0', alignItems: 'center', justifyContent: 'center'},
  track: {flex: 1, height: 6, borderRadius: 3, backgroundColor: '#e2e8f0', overflow: 'hidden'},
  trackFill: {height: 6, backgroundColor: theme.accent},
  tabBar: {flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.border, marginBottom: 10},
  tab: {paddingVertical: 8, paddingHorizontal: 14},
  tabActive: {borderBottomWidth: 2, borderColor: theme.accent},
  tabText: {color: theme.muted, fontWeight: '600'},
  tabTextActive: {color: theme.accent},
  modalBackdrop: {position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'flex-end'},
  modalSheet: {backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 18},
  unknown: {padding: 8, borderWidth: 1, borderStyle: 'dashed', borderColor: '#dc2626', borderRadius: 8},
});
