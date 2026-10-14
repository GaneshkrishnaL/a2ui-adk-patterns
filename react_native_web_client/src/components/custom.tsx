/**
 * React Native implementations of the CUSTOM catalog components declared in ../a2ui/catalog.ts.
 *
 * These are the "5% path": domain widgets that are awkward to compose from primitives.
 * The agent can only emit them when the surface was created with `catalogId: SOCIAL_CATALOG_ID`.
 */
import React from 'react';
import {Image, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import type {A2uiComponentProps} from '../a2ui/A2uiRenderer';
import {theme} from './theme';

const fmt = new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1});

/** StatTile: big compact number + label, optional accent + tap action. */
export const StatTileRN = ({props}: A2uiComponentProps) => {
  const accent = theme.accents[(props.accent as keyof typeof theme.accents) ?? 'blue'] ?? theme.accents.blue;
  const value = typeof props.value === 'number' ? fmt.format(props.value) : String(props.value ?? '-');
  const Wrapper: any = typeof props.action === 'function' ? Pressable : View;
  return (
    <Wrapper role={typeof props.action === "function" ? "button" : undefined} onPress={props.action} style={[s.tile, {backgroundColor: accent.bg}, props.weight ? {flex: props.weight} : null]}>
      <Text style={[s.tileValue, {color: accent.fg}]}>{value}</Text>
      <Text style={[s.tileLabel, {color: accent.fg}]}>{String(props.label ?? '')}</Text>
    </Wrapper>
  );
};

/** ProfileHeader: avatar + name + handle (+ verified badge) with an optional trailing child. */
export const ProfileHeaderRN = ({props, renderChild}: A2uiComponentProps) => (
  <View style={s.header}>
    <Image source={{uri: String(props.avatarUrl ?? '')}} style={s.avatar} />
    <View style={{flex: 1, gap: 2}}>
      <View style={{flexDirection: 'row', alignItems: 'center', gap: 6}}>
        <Text style={s.name}>{String(props.name ?? '')}</Text>
        {props.verified ? (
          <View style={s.badge}>
            <Text style={s.badgeText}>✓</Text>
          </View>
        ) : null}
      </View>
      <Text style={s.handle}>{String(props.handle ?? '')}</Text>
    </View>
    {props.trailing ? renderChild(props.trailing) : null}
  </View>
);

/** ChipStrip: horizontally scrolling container for any children. */
export const ChipStripRN = ({props, renderChild}: A2uiComponentProps) => (
  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.strip}>
    {Array.isArray(props.children)
      ? props.children.map((c: any) => (
          <View key={typeof c === 'string' ? c : `${c.id}@${c.basePath}`} style={s.stripItem}>
            {renderChild(c)}
          </View>
        ))
      : null}
  </ScrollView>
);

const s = StyleSheet.create({
  tile: {borderRadius: 14, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', minWidth: 92},
  tileValue: {fontSize: 22, fontWeight: '800'},
  tileLabel: {fontSize: 12, fontWeight: '600', opacity: 0.8, marginTop: 2},
  header: {flexDirection: 'row', alignItems: 'center', gap: 14},
  avatar: {width: 64, height: 64, borderRadius: 32, borderWidth: 2, borderColor: theme.accent},
  name: {fontSize: 18, fontWeight: '700', color: theme.text},
  handle: {fontSize: 13, color: theme.muted},
  badge: {width: 18, height: 18, borderRadius: 9, backgroundColor: '#0ea5e9', alignItems: 'center', justifyContent: 'center'},
  badgeText: {color: '#fff', fontSize: 11, fontWeight: '800'},
  strip: {flexDirection: 'row', gap: 10, paddingVertical: 4},
  stripItem: {},
});
