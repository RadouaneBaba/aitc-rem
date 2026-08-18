import type { Redactor } from '../redaction/redact';
import type { FidelityFlag, SemanticNode, SemanticSnapshot } from '../types/recording';
import {
  hidden,
  isFormControl,
  isLandmark,
  isLiveRegion,
  isTransparent,
  nameOf,
  ownText,
  rawValueOf,
  roleOf,
  stateOf,
} from './a11y';

/**
 * SS6.3 -- semantic snapshots, never raw DOM HTML.
 *
 *   Raw DOM HTML      50-200 KB   signal buried in framework noise
 *   Semantic snapshot   2-6 KB    exactly what a human perceives
 *
 * Raw DOM does not merely cost more: it overflows the context window and
 * produces incoherent output on any model.
 */

/**
 * A snapshot past this many nodes is truncated rather than allowed to grow
 * unbounded on an enterprise page. SS17.2 names snapshot performance as the
 * main unvalidated capture assumption, so the cap is explicit and the fact that
 * it was hit is reported on the snapshot instead of silently shortening it.
 */
const MAX_NODES = 400;
const MAX_DEPTH = 25;

export interface SnapshotResult {
  snapshot: SemanticSnapshot;
  flags: FidelityFlag[];
}

interface BuildCtx {
  redactor: Redactor;
  budget: { left: number };
  flags: Set<FidelityFlag>;
  seen: WeakSet<Element>;
}

/**
 * Scope per SS6.3: the target's nearest landmark or dialog ancestor. Capturing
 * the whole tree twice per action across 120 actions is wasteful and slow on
 * large enterprise apps. The expensive view is available on demand through the
 * get_full_snapshot tool -- cheap by default, costly on request, which is
 * itself an agentic decision.
 */
export function scopeRootFor(target: Element | null, doc: Document): Element {
  let el: Element | null = target;
  while (el && el !== doc.documentElement) {
    if (isLandmark(roleOf(el))) return el;
    const root = el.getRootNode();
    el = el.parentElement ?? (root instanceof ShadowRoot ? root.host : null);
  }
  return doc.body ?? doc.documentElement;
}

export function buildSnapshot(
  target: Element | null,
  doc: Document,
  redactor: Redactor,
  opts: { full?: boolean; at?: number } = {},
): SnapshotResult {
  const ctx: BuildCtx = {
    redactor,
    budget: { left: MAX_NODES },
    flags: new Set(),
    seen: new WeakSet(),
  };

  const root = opts.full ? (doc.body ?? doc.documentElement) : scopeRootFor(target, doc);
  const rootNode = buildNode(root, '0', ctx, 0) ?? {
    ref: '0',
    role: roleOf(root) || 'generic',
    name: '',
  };

  // Live regions are collected document-wide, outside the scope, because the
  // outcome of an action routinely renders far from the element clicked.
  const liveRegions: SemanticNode[] = [];
  let liveIndex = 0;
  for (const el of collectLiveRegions(doc)) {
    if (root.contains(el)) continue;
    const node = buildNode(el, `live.${liveIndex}`, ctx, 0);
    if (node) {
      liveRegions.push(node);
      liveIndex += 1;
    }
  }

  const scopeRole = roleOf(root);
  const snapshot: SemanticSnapshot = {
    capturedAt: opts.at ?? now(),
    url: doc.location?.href ?? '',
    title: doc.title,
    scope: opts.full ? 'full' : 'scoped',
    root: rootNode,
    liveRegions,
  };
  if (!opts.full) {
    snapshot.scopeRoot = {
      role: scopeRole || 'generic',
      name: nameOf(root),
      ...(isLandmark(scopeRole) ? { landmark: scopeRole } : {}),
    };
  }
  if (ctx.budget.left <= 0) snapshot.truncated = true;

  return { snapshot, flags: [...ctx.flags] };
}

function buildNode(el: Element, ref: string, ctx: BuildCtx, depth: number): SemanticNode | null {
  if (ctx.budget.left <= 0 || depth > MAX_DEPTH) return null;
  if (ctx.seen.has(el)) return null;
  ctx.seen.add(el);
  if (hidden(el)) return null;

  const role = roleOf(el);
  const name = nameOf(el);
  const children = buildChildren(el, ref, ctx, depth);

  // A structural wrapper with nothing to say is dropped and its children are
  // hoisted. This is most of what keeps a snapshot at 2-6 KB rather than 200.
  if (isTransparent(role) && !name && !isFormControl(el)) {
    if (children.length === 0) {
      const text = ownText(el);
      if (!text) return null;
      ctx.budget.left -= 1;
      return { ref, role: 'text', name: ctx.redactor.redactText(text) };
    }
    if (children.length === 1) return reref(children[0]!, ref);
    ctx.budget.left -= 1;
    return { ref, role: 'group', name: '', children: renumber(children, ref) };
  }

  ctx.budget.left -= 1;

  const rawValue = rawValueOf(el);
  const state = stateOf(el);
  const node: SemanticNode = {
    ref,
    role: role || 'generic',
    name: ctx.redactor.redactText(name || ownText(el)),
  };
  if (rawValue !== null) node.value = ctx.redactor.redactFieldValue(el, rawValue);
  if (state.length) node.state = state;
  if (isLandmark(role)) node.landmark = role;
  if (children.length) node.children = renumber(children, ref);

  // no_accessible_name is deliberately NOT raised here. SS6.8 describes it as
  // a statement about the element that was acted on ("my description of this
  // element may be wrong"), and raising it for any unnamed node anywhere in
  // scope flagged almost every event in practice, which is the same as
  // flagging none of them. The target check in describeTarget() owns it.

  return node;
}

function buildChildren(el: Element, ref: string, ctx: BuildCtx, depth: number): SemanticNode[] {
  const out: SemanticNode[] = [];

  // Open shadow roots are reachable via element.shadowRoot. Closed ones are
  // unreachable by any means, CDP included, so they are flagged rather than
  // guessed at (SS6.8).
  const shadow = (el as HTMLElement).shadowRoot;
  if (shadow) {
    for (const child of Array.from(shadow.children)) {
      const node = buildNode(child, `${ref}.${out.length}`, ctx, depth + 1);
      if (node) out.push(node);
    }
  } else if (isCustomElement(el) && el.children.length === 0 && !ownText(el)) {
    ctx.flags.add('closed_shadow_root');
  }

  for (const child of Array.from(el.children)) {
    const tag = child.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEMPLATE' || tag === 'NOSCRIPT') continue;

    if (tag === 'IFRAME') {
      // The frame's contents belong to its own content script, which reports
      // them separately under its own FramePath.
      ctx.budget.left -= 1;
      out.push({
        ref: `${ref}.${out.length}`,
        role: 'iframe',
        name: child.getAttribute('title') ?? child.getAttribute('name') ?? '',
      });
      continue;
    }

    const node = buildNode(child, `${ref}.${out.length}`, ctx, depth + 1);
    if (node) out.push(node);
  }

  return out;
}

/**
 * Refs are structural paths over EMITTED nodes, so dropping a transparent
 * wrapper does not leave a gap in the numbering.
 */
function renumber(children: SemanticNode[], parentRef: string): SemanticNode[] {
  return children.map((child, i) => reref(child, `${parentRef}.${i}`));
}

function reref(node: SemanticNode, ref: string): SemanticNode {
  const next: SemanticNode = { ...node, ref };
  if (node.children) next.children = node.children.map((c, i) => reref(c, `${ref}.${i}`));
  return next;
}

function isCustomElement(el: Element): boolean {
  return el.tagName.includes('-');
}

export function collectLiveRegions(doc: Document): Element[] {
  const selector = [
    '[role=alert]',
    '[role=status]',
    '[role=log]',
    '[role=alertdialog]',
    '[aria-live=polite]',
    '[aria-live=assertive]',
    'output',
  ].join(',');
  try {
    return Array.from(doc.querySelectorAll(selector)).filter(
      (el) => isLiveRegion(el) && !hidden(el),
    );
  } catch {
    return [];
  }
}

export interface FlatNode {
  ref: string;
  role: string;
  name: string;
  value?: string;
  state?: string[];
  path: string;
}

/** Flatten for diffing and for the find_text grounding lookup. */
export function flatten(node: SemanticNode, path: string[] = []): FlatNode[] {
  const here: FlatNode = {
    ref: node.ref,
    role: node.role,
    name: node.name,
    path: path.join(' > '),
  };
  if (node.value !== undefined) here.value = node.value;
  if (node.state) here.state = node.state;

  const label = node.name ? `${node.role} "${node.name}"` : node.role;
  const rest = (node.children ?? []).flatMap((c) => flatten(c, [...path, label]));
  return [here, ...rest];
}

export function flattenSnapshot(snap: SemanticSnapshot): FlatNode[] {
  return [...flatten(snap.root), ...snap.liveRegions.flatMap((n) => flatten(n))];
}

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}
