import type { DiffNode, NodeChange, SemanticSnapshot, SnapshotDiff } from '../types/recording';
import { type FlatNode, flattenSnapshot } from './snapshot';

/**
 * Computed at capture time (SS6.2) so the pipeline never has to re-derive it,
 * and so `get_diff` is a lookup rather than a computation.
 *
 * Nodes are matched by identity rather than by ref: a ref is a structural path,
 * and inserting one row shifts every ref below it. Matching on (role, name,
 * path) instead means adding a row reports one addition, not forty changes.
 */
function identity(n: FlatNode): string {
  return `${n.path}|${n.role}|${n.name}`;
}

function toDiffNode(n: FlatNode): DiffNode {
  const out: DiffNode = { ref: n.ref, role: n.role, name: n.name };
  if (n.value !== undefined) out.value = n.value;
  if (n.state) out.state = n.state;
  if (n.path) out.path = n.path;
  return out;
}

export function diffSnapshots(before: SemanticSnapshot, after: SemanticSnapshot): SnapshotDiff {
  const beforeNodes = flattenSnapshot(before);
  const afterNodes = flattenSnapshot(after);

  // Duplicate identities (table rows that read identically) are matched in
  // order, so N identical rows becoming N-1 reports one removal.
  const beforeByKey = new Map<string, FlatNode[]>();
  for (const n of beforeNodes) {
    const key = identity(n);
    const bucket = beforeByKey.get(key);
    if (bucket) bucket.push(n);
    else beforeByKey.set(key, [n]);
  }

  const added: DiffNode[] = [];
  const changed: NodeChange[] = [];
  const matched = new Set<FlatNode>();

  for (const a of afterNodes) {
    const bucket = beforeByKey.get(identity(a));
    const b = bucket?.shift();
    if (!b) {
      added.push(toDiffNode(a));
      continue;
    }
    matched.add(b);

    const fields: string[] = [];
    if (b.value !== a.value) fields.push('value');
    if ((b.state ?? []).join(',') !== (a.state ?? []).join(',')) fields.push('state');
    if (fields.length) {
      changed.push({ before: toDiffNode(b), after: toDiffNode(a), fields });
    }
  }

  const removed: DiffNode[] = [];
  for (const bucket of beforeByKey.values()) {
    for (const b of bucket) {
      if (!matched.has(b)) removed.push(toDiffNode(b));
    }
  }

  const diff: SnapshotDiff = { added, removed, changed };
  if (before.url !== after.url) diff.urlChanged = { from: before.url, to: after.url };
  if (before.title !== after.title) diff.titleChanged = { from: before.title, to: after.title };
  return diff;
}

/** Did this action produce something a tester would call an outcome? */
export function hasOutcomeSignal(diff: SnapshotDiff): boolean {
  const LIVE = new Set(['alert', 'status', 'log', 'alertdialog']);
  return (
    diff.added.some((n) => LIVE.has(n.role)) ||
    diff.urlChanged !== undefined ||
    diff.changed.length > 0
  );
}
