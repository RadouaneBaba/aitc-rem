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
 *   Semantic snapshot  10-40 KB   exactly what a human perceives
 *
 * Raw DOM does not merely cost more: it overflows the context window and
 * produces incoherent output on any model.
 *
 * The snapshot is of the WHOLE DOCUMENT. It was scoped to the clicked element's
 * nearest landmark until 2026-08-28, and that -- not any downstream prompt --
 * is what made 30-50% of events on real sites record no observed change at all.
 * See `scopeRootFor` for the mechanism and `MAX_NODES` for why widening the
 * scope without raising the cap would have been a no-op.
 *
 * Storing more is cheap and it is not what reaches a model: the recording is
 * indexed on the server and the author retrieves through tools, so a bigger
 * snapshot costs disk, not context.
 */

/**
 * A snapshot past this many nodes is truncated rather than allowed to grow
 * unbounded on an enterprise page. SS17.2 names snapshot performance as the
 * main unvalidated capture assumption, so the cap is explicit and the fact that
 * it was hit is reported on the snapshot instead of silently shortening it.
 *
 * **This was 400, and that number is why "full capture is affordable" looked
 * settled when it was not.** Measured on the two real recordings on disk:
 * 30 of 34 events on `rec_MT7MXBS9B2VB` and 9 of 15 on `rec_MTA7A2XHHH22`
 * carried `truncated: true` on BOTH snapshots. Every "a full page is ~29 KB"
 * figure in docs/REBUILD_FINDINGS.md is therefore the measurement of a cap, not
 * of a page -- and raising `full` to the default while the cap stayed at 400
 * would have changed nothing on exactly the pages that matter.
 *
 * Worse, the budget is spent depth-first in document order, so the cut lands at
 * the BOTTOM of the page. On the storefront the last nodes that fit were the
 * footer's payment icons; a product grid below the fold would simply not be
 * there. That is a second, independent way to record an empty candidate set,
 * and it was being attributed entirely to scoping.
 *
 * 3000 is chosen so a real commercial page fits with room over: that
 * storefront's whole document reached its own footer at ~405 nodes. `truncated`
 * stays the alarm, and `nodeCount` below is what makes the real cost of a
 * recording readable without re-flattening it.
 */
const MAX_NODES = 3000;
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
 * The target's nearest landmark or dialog ancestor.
 *
 * This used to decide what got CAPTURED, and that was the defect of
 * 2026-08-28. The argument for it was that the whole tree twice per action is
 * wasteful, and that `get_full_snapshot` was the escape hatch. Neither half
 * held: nothing in the extension ever asked for the full view, and the server's
 * `get_full_snapshot` was merging scoped snapshots of data that had never been
 * recorded -- the page is gone by the time the server runs.
 *
 * What it cost: `scopeRootFor` walks to the NEAREST landmark, so a tester
 * clicking inside a filter widget that is its own `region` captured 1.2 KB and
 * an empty diff, while the product list the test was about was never captured
 * at all. Which is most of what testing is.
 *
 * It is kept because it still answers a real question -- which part of the page
 * the tester was working in -- and because the keyhole has to stay reproducible
 * in a test. It no longer decides what is captured.
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
  opts: { at?: number } = {},
): SnapshotResult {
  const ctx: BuildCtx = {
    redactor,
    budget: { left: MAX_NODES },
    flags: new Set(),
    seen: new WeakSet(),
  };

  // Always the document. Never `scopeRootFor(target)` -- see its comment.
  //
  // Taking the same root every time also closes the second half of the defect,
  // silently: `scopeRootFor` was re-evaluated for `after`, so a click that
  // detached its own landmark ancestor fell back to document.body and every
  // node's path changed. The diff then read +408 added / -405 removed on a
  // 405-node tree, which was being read downstream as "the product grid
  // re-rendered". It was noise. `before` and `after` are now comparable by
  // construction.
  const root = doc.body ?? doc.documentElement;

  // The root is built explicitly rather than through `buildNode`, and that is
  // load-bearing under full capture.
  //
  // `buildNode` hoists a transparent wrapper with exactly one child. `body` is
  // `generic`, so on a page whose body has one child the ROOT of the snapshot
  // became that child -- and the moment anything was appended to body (a modal,
  // a toast, a React portal, all of which are normal) body had two children,
  // the hoist stopped, and every node in the document gained a path segment.
  // Identity is `path|role|name`, so nothing matched: one insertion reported the
  // whole page as removed and re-added.
  //
  // That is the same family of defect as the scope root moving between `before`
  // and `after`, and it is the better explanation for the +408 added / -405
  // removed diffs on `rec_MTA7A2XHHH22` that docs/REBUILD_FINDINGS.md reads as
  // "the product grid re-rendered with hundreds of changes". They were noise.
  //
  // Pinning the root gives every path a stable prefix, so a diff reports what
  // changed.
  const rootChildren = buildChildren(root, '0', ctx, 0);
  const rootNode: SemanticNode = {
    ref: '0',
    role: roleOf(root) || 'generic',
    name: '',
    ...(rootChildren.length ? { children: renumber(rootChildren, '0') } : {}),
  };

  // Live regions were collected document-wide because the outcome of an action
  // routinely renders far from the element clicked. With the whole document
  // captured they are already in `root`, so this loop now finds nothing and the
  // list is empty -- which is correct, and nothing downstream breaks:
  // `hasOutcomeSignal` reads alert/status roles off the diff, and the server's
  // flattener tolerates an empty list. Kept rather than deleted because a
  // future targeted capture would need it back.
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

  const snapshot: SemanticSnapshot = {
    capturedAt: opts.at ?? now(),
    url: doc.location?.href ?? '',
    title: doc.title,
    scope: 'full',
    root: rootNode,
    liveRegions,
    // What this page actually cost, so the question "is full capture
    // affordable" is answerable from any recording rather than re-litigated
    // from a cap that was being mistaken for a measurement.
    nodeCount: MAX_NODES - ctx.budget.left,
  };
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
      return { ref, role: 'text', name: ctx.redactor.redactKnownSecrets(text) };
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
    // Read exactly, not pattern-scanned.
    //
    // `redactText` ran here over every node of every snapshot, which is
    // redaction applied to what the application DISPLAYED rather than to what
    // the tester TYPED. On one storefront listing it produced 214 parameters,
    // all classified as phone numbers. Measured: what the rule actually matches
    // in page text is dates -- `"Updated 2026-08-28 14:32"` becomes
    // `<<phone_n>>` -- and a date on a page is routinely the thing a test
    // asserts on.
    //
    // What IS still replaced here is any exact value already known to be a
    // secret -- see `redactKnownSecrets`. Capturing the whole page made that
    // necessary: an application that displays a value the tester also typed (a
    // "show password" toggle, a confirmation screen echoing an email) now
    // reaches the snapshot, and no pattern rule would catch it.
    //
    // The tester's own input is still redacted by context, on `value` below.
    // That is the rule that has never been wrong, and it is the one SS7 is
    // actually about.
    name: ctx.redactor.redactKnownSecrets(name || ownText(el)),
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
