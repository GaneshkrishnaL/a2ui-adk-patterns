/**
 * React (Native) binding layer over @a2ui/web_core.
 *
 *   SurfaceModel  ──►  ComponentContext  ──►  GenericBinder  ──►  resolved props  ──►  RN component
 *
 * `GenericBinder` (from web_core) does all the protocol work: it reads the Zod schema of the
 * component, resolves `{path}` / `{call}` dynamic values against the DataModel, turns `action`
 * payloads into dispatchable closures, evaluates `checks` into `isValid` / `validationErrors`,
 * expands collection-bound `children` templates, and re-emits whenever bound data changes.
 *
 * This file is framework glue only (~120 lines). It has no knowledge of specific components.
 */
import React, {createContext, useContext, useEffect, useMemo, useState} from 'react';
import {
  ComponentContext,
  GenericBinder,
  type DataContext,
  type ResolvedChildRef,
  type SurfaceModel,
} from '@a2ui/web_core/v0_9';
import type {ComponentApi} from '@a2ui/web_core/catalog';

/** Child reference as handed to a component by the binder. */
export type ChildRef = string | ResolvedChildRef;

/** What every React Native A2UI component receives. */
export interface A2uiComponentProps<P = Record<string, any>> {
  /** Resolved, reactive props (dynamic values already evaluated). */
  props: P & {isValid?: boolean; validationErrors?: string[]};
  /** Render a child by id (static) or by resolved template ref. */
  renderChild: (ref: ChildRef | undefined | null) => React.ReactNode;
  /** The underlying web_core context (data model access, dispatchAction, theme). */
  context: ComponentContext;
}

export type A2uiComponentImpl = React.ComponentType<A2uiComponentProps<any>>;
export type ComponentRegistry = Record<string, A2uiComponentImpl>;

interface SurfaceCtx {
  surface: SurfaceModel<ComponentApi>;
  registry: ComponentRegistry;
}
const SurfaceReactContext = createContext<SurfaceCtx | null>(null);

/**
 * Hook: binds one component id to its schema and returns live props.
 */
function useBoundComponent(
  surface: SurfaceModel<ComponentApi>,
  componentId: string,
  basePath: string,
  parentDataContext?: DataContext,
  index?: number,
) {
  const model = surface.componentsModel.get(componentId);
  const api = model
    ? (model.catalog ?? surface.defaultCatalog).components.get(model.type)
    : undefined;

  // ComponentContext + GenericBinder are created once per (surface, id, path).
  const bound = useMemo(() => {
    if (!model || !api) return null;
    const context = new ComponentContext(surface, componentId, basePath, parentDataContext, index);
    const binder = new GenericBinder<Record<string, any>>(context, api.schema);
    return {context, binder};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surface, componentId, basePath, parentDataContext, index, model, api]);

  const [props, setProps] = useState<Record<string, any>>(() => bound?.binder.snapshot ?? {});

  useEffect(() => {
    if (!bound) return;
    setProps({...bound.binder.snapshot});
    const sub = bound.binder.subscribe(next => setProps({...next}));
    return () => sub.unsubscribe();
  }, [bound]);

  return {model, api, props, context: bound?.context};
}

/** Renders a single A2UI component node (and, through renderChild, its subtree). */
export function A2uiNode({
  componentId,
  basePath = '/',
  parentDataContext,
  index,
}: {
  componentId: string;
  basePath?: string;
  parentDataContext?: DataContext;
  index?: number;
}) {
  const ctx = useContext(SurfaceReactContext);
  if (!ctx) throw new Error('A2uiNode must be rendered inside <A2uiSurface>.');
  const {surface, registry} = ctx;
  const {model, api, props, context} = useBoundComponent(
    surface,
    componentId,
    basePath,
    parentDataContext,
    index,
  );

  if (!model) {
    // Component may arrive in a later updateComponents message (streaming) - render nothing.
    return null;
  }
  const Impl = registry[model.type] ?? registry['__unknown__'];
  if (!Impl || !api || !context) return null;

  const renderChild = (ref: ChildRef | undefined | null): React.ReactNode => {
    if (!ref) return null;
    if (typeof ref === 'string') {
      return (
        <A2uiNode
          key={ref}
          componentId={ref}
          basePath={basePath}
          parentDataContext={parentDataContext}
          index={index}
        />
      );
    }
    // Template-expanded child: scope the data context to the item path.
    const itemIndex = Number(ref.basePath.split('/').pop());
    return (
      <A2uiNode
        key={`${ref.id}@${ref.basePath}`}
        componentId={ref.id}
        basePath={ref.basePath}
        parentDataContext={context.dataContext}
        index={Number.isFinite(itemIndex) ? itemIndex : undefined}
      />
    );
  };

  return <Impl props={props} renderChild={renderChild} context={context} />;
}

/** Renders a whole surface starting at its root component. */
export function A2uiSurface({
  surface,
  registry,
}: {
  surface: SurfaceModel<ComponentApi>;
  registry: ComponentRegistry;
}) {
  // Re-render when components are (re)created so late-arriving nodes appear (streaming).
  const [, bump] = useState(0);
  useEffect(() => {
    const s1 = surface.componentsModel.onCreated.subscribe(() => bump(n => n + 1));
    const s2 = surface.componentsModel.onDeleted.subscribe(() => bump(n => n + 1));
    return () => {
      s1.unsubscribe();
      s2.unsubscribe();
    };
  }, [surface]);

  const value = useMemo(() => ({surface, registry}), [surface, registry]);
  return (
    <SurfaceReactContext.Provider value={value}>
      <A2uiNode componentId={surface.rootId} />
    </SurfaceReactContext.Provider>
  );
}
