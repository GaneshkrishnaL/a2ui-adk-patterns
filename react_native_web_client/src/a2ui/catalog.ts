/**
 * Catalog definitions for the React Native renderer.
 *
 * Two catalogs are registered with the MessageProcessor:
 *
 *  1. `basicCatalogRN`  - the official A2UI v0.9 Basic Catalog (18 components, 14 functions).
 *                         Its id is the canonical URL, so JSON produced by the A2UI Composer
 *                         (which targets the basic catalog) renders unmodified.
 *
 *  2. `socialCatalog`   - a custom catalog that EXTENDS the basic catalog with domain
 *                         components (`StatTile`, `ProfileHeader`, `VerifiedBadge`) and a
 *                         custom client-side function (`initials`).
 *
 * The *schemas* come straight from `@a2ui/web_core` (pure Zod, no DOM) - only the visual
 * implementation (in ../components) is React Native.
 */
import {z} from 'zod';
import {
  Catalog,
  createFunctionImplementation,
  type ComponentApi,
  type FunctionImplementation,
} from '@a2ui/web_core/catalog';
import {
  ActionSchema,
  ChildListSchema,
  ComponentIdSchema,
  DynamicBooleanSchema,
  DynamicNumberSchema,
  DynamicStringSchema,
} from '@a2ui/web_core/v0_9';
import {
  BASIC_COMPONENTS,
  BASIC_FUNCTIONS,
  BasicCatalogThemeSchema,
} from '@a2ui/web_core/v0_9/basic_catalog';

export const BASIC_CATALOG_ID = 'https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json';
export const SOCIAL_CATALOG_ID = 'demo.example.com:social_profile_catalog';

// ---------------------------------------------------------------------------
// Custom component APIs (schema contract shared with the agent / LLM prompt)
// ---------------------------------------------------------------------------
// NOTE: the `REF:#/$defs/...` describe() markers tell web_core's GenericBinder how to treat
// each property: DynamicString/Number/Boolean => reactive data binding, Action => dispatchable
// closure, ChildList/ComponentId => child component references.

/** A compact metric tile: big number + label + optional accent colour. */
export const StatTileApi = {
  name: 'StatTile',
  schema: z
    .object({
      weight: z.number().optional(),
      label: DynamicStringSchema.describe('REF:#/$defs/DynamicString|Short label under the number.'),
      value: DynamicNumberSchema.describe('REF:#/$defs/DynamicNumber|Numeric value to display.'),
      accent: z.enum(['blue', 'green', 'purple', 'orange']).default('blue').optional(),
      action: ActionSchema.describe('REF:#/$defs/Action|Optional tap action.').optional(),
    })
    .strict(),
} satisfies ComponentApi;

/** Avatar + name + handle + verified flag in one branded header. */
export const ProfileHeaderApi = {
  name: 'ProfileHeader',
  schema: z
    .object({
      weight: z.number().optional(),
      avatarUrl: DynamicStringSchema.describe('REF:#/$defs/DynamicString|Avatar image URL.'),
      name: DynamicStringSchema.describe('REF:#/$defs/DynamicString|Display name.'),
      handle: DynamicStringSchema.describe('REF:#/$defs/DynamicString|@handle.'),
      verified: DynamicBooleanSchema.describe(
        'REF:#/$defs/DynamicBoolean|Shows a verified badge when true.',
      ).optional(),
      trailing: ComponentIdSchema.describe(
        'REF:#/$defs/ComponentId|Optional component rendered on the right (e.g. a Button).',
      ).optional(),
    })
    .strict(),
} satisfies ComponentApi;

/** A horizontally scrolling strip of children (custom layout container). */
export const ChipStripApi = {
  name: 'ChipStrip',
  schema: z
    .object({
      weight: z.number().optional(),
      children: ChildListSchema.describe(
        'REF:#/$defs/ChildList|Children rendered as a horizontal, scrollable strip.',
      ),
    })
    .strict(),
} satisfies ComponentApi;

export const CUSTOM_COMPONENTS: ComponentApi[] = [StatTileApi, ProfileHeaderApi, ChipStripApi];

// ---------------------------------------------------------------------------
// Custom client-side function: initials("Sarah Chen") -> "SC"
// ---------------------------------------------------------------------------
export const initialsFunction: FunctionImplementation = createFunctionImplementation(
  {
    name: 'initials',
    returnType: 'string',
    description: 'Returns the upper-case initials of a full name.',
    schema: z.object({
      value: DynamicStringSchema.describe('REF:#/$defs/DynamicString|Full name.'),
    }),
  },
  args => {
    const name = String(args.value ?? '');
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(part => part[0]!.toUpperCase())
      .join('');
  },
);

// ---------------------------------------------------------------------------
// Catalog instances
// ---------------------------------------------------------------------------
export const basicCatalogRN = new Catalog(
  BASIC_CATALOG_ID,
  '0.9',
  BASIC_COMPONENTS,
  BASIC_FUNCTIONS,
  BasicCatalogThemeSchema,
);

export const socialCatalog = new Catalog(
  SOCIAL_CATALOG_ID,
  '0.9',
  [...BASIC_COMPONENTS, ...CUSTOM_COMPONENTS],
  [...BASIC_FUNCTIONS, initialsFunction],
  BasicCatalogThemeSchema,
  'Social profile catalog: all basic components plus StatTile, ProfileHeader and ChipStrip.',
);

export const ALL_CATALOGS = [basicCatalogRN, socialCatalog];
