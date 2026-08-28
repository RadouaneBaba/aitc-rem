#!/usr/bin/env python
"""What does capturing the whole page actually cost?

    "A full page is ~29 KB / ~7.4k tokens -- which is already what the large
     events cost today."  -- docs/REBUILD_FINDINGS.md SS1

That sentence closed the open question about whether full capture was
affordable, and it was measured on snapshots that had **all hit a 400-node
cap**: 30 of 34 events on `rec_MT7MXBS9B2VB` and 9 of 15 on `rec_MTA7A2XHHH22`
carried `truncated: true` on both sides. It described the cap, not the page.

This script exists so that number is never guessed at again. Point it at any
recording and it reports what capture actually cost -- per event and in total --
and says plainly whether the node budget is still binding.

    python scripts/capture_cost.py                          # every recording
    python scripts/capture_cost.py tests/fixtures/*.json
    python scripts/capture_cost.py --id rec_MTA7A2XHHH22

`nodeCount` is written by the recorder. Recordings made before 2026-08-28 do not
carry it, so it is recomputed by walking the tree -- which is also how this
script can put the old scoped corpus and the new full one in the same table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Mirrors MAX_NODES in extension/src/content/snapshot.ts. Reported rather than
#: enforced: this script's job is to say whether the cap is binding, and it
#: cannot do that if it does not know what the cap is.
MAX_NODES = 3000

#: Rough, and deliberately so. Snapshots are JSON with short repeated keys, so
#: the usual 4-chars-per-token rule is closer than it is on prose. The number is
#: here to make "is this affordable" answerable at a glance, not to bill anyone.
CHARS_PER_TOKEN = 4


def count_nodes(node: dict[str, Any]) -> int:
    return 1 + sum(count_nodes(c) for c in node.get("children") or [])


def snapshot_cost(snap: dict[str, Any] | None) -> tuple[int, int, bool]:
    """(nodes, bytes, truncated) for one snapshot."""
    if not snap:
        return 0, 0, False
    nodes = snap.get("nodeCount")
    if nodes is None:
        nodes = count_nodes(snap["root"]) + sum(
            count_nodes(n) for n in snap.get("liveRegions") or []
        )
    return int(nodes), len(json.dumps(snap)), bool(snap.get("truncated"))


def report(path: Path, *, per_event: bool) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    events = doc.get("events", [])
    scopes = {e.get("before", {}).get("scope") for e in events} | {
        e.get("after", {}).get("scope") for e in events
    }

    print(f"\n{doc.get('id', path.stem)}  ({len(events)} events)")
    print(f"  objective: {doc.get('objective') or '(none stated)'}")
    print(f"  capture:   {'/'.join(sorted(s for s in scopes if s)) or 'unknown'}")

    total_nodes = total_bytes = truncated = empty_diffs = 0
    biggest = (0, "")

    if per_event:
        print(f"  {'event':<9} {'nodes b/a':>12} {'KB b+a':>8} {'diff +/-/~':>16}  trunc")

    for event in events:
        nb, bb, tb = snapshot_cost(event.get("before"))
        na, ba, ta = snapshot_cost(event.get("after"))
        _, bt, tt = snapshot_cost(event.get("transient"))

        nodes, size = max(nb, na), bb + ba + bt
        total_nodes += nodes
        total_bytes += size
        if tb or ta or tt:
            truncated += 1
        if size > biggest[0]:
            biggest = (size, event["id"])

        diff = event.get("diff") or {}
        added, removed, changed = (
            len(diff.get("added") or []),
            len(diff.get("removed") or []),
            len(diff.get("changed") or []),
        )
        # A diff with nothing in it and no navigation is an event that recorded
        # no observed change at all. This is the number the rebuild is about.
        if not (added or removed or changed or diff.get("urlChanged")):
            empty_diffs += 1

        if per_event:
            mark = "TRUNC" if (tb or ta or tt) else ""
            print(
                f"  {event['id']:<9} {f'{nb}/{na}':>12} {size / 1024:>8.1f} "
                f"{f'+{added}/-{removed}/~{changed}':>16}  {mark}"
            )

    n = len(events) or 1
    print(
        f"  totals:    {total_bytes / 1024:.0f} KB stored, "
        f"~{total_bytes // CHARS_PER_TOKEN:,} tokens IF it were all sent"
    )
    print(
        f"  per event: {total_bytes / n / 1024:.1f} KB, {total_nodes // n} nodes"
        f"   (largest {biggest[0] / 1024:.1f} KB at {biggest[1]})"
    )
    print(f"  parameters: {len(doc.get('parameters') or [])}")

    # The two findings this script exists to keep honest.
    if truncated:
        # Deliberately does not name a number. The flag was written by whatever
        # cap was in force when the recording was made -- 400 before 2026-08-28
        # -- and the whole point of this warning is that a truncated snapshot
        # measures its cap rather than its page.
        print(
            f"  !! {truncated}/{len(events)} events report themselves truncated. "
            f"Every size above is that recording's node CAP, not the page. Do not "
            f"read these as a measurement of what capture costs."
        )
    else:
        print(f"  ok: nothing truncated (cap is {MAX_NODES}); these sizes are real pages.")

    if empty_diffs:
        share = 100 * empty_diffs / len(events) if events else 0
        print(
            f"  !! {empty_diffs}/{len(events)} events ({share:.0f}%) recorded NO observed "
            f"change. That is the defect docs/REBUILD_FINDINGS.md is about."
        )

    return {
        "id": doc.get("id"),
        "events": len(events),
        "bytes": total_bytes,
        "truncated": truncated,
        "emptyDiffs": empty_diffs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="recording.json files; default: recordings/")
    parser.add_argument("--id", help="one recording id under recordings/")
    parser.add_argument("--quiet", action="store_true", help="totals only, no per-event table")
    args = parser.parse_args(argv)

    if args.id:
        paths = [REPO_ROOT / "recordings" / args.id / "recording.json"]
    elif args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = sorted((REPO_ROOT / "recordings").glob("*/recording.json"))
        paths += sorted((REPO_ROOT / "tests" / "fixtures").glob("*.recording.json"))

    paths = [p for p in paths if p.is_file()]
    if not paths:
        print("no recordings found", file=sys.stderr)
        return 1

    rows = [report(p, per_event=not args.quiet) for p in paths]

    print(f"\n{'=' * 60}")
    worst = max(rows, key=lambda r: r["bytes"] / max(r["events"], 1))
    print(
        f"{len(rows)} recording(s). Heaviest per event: {worst['id']} at "
        f"{worst['bytes'] / max(worst['events'], 1) / 1024:.1f} KB."
    )
    capped = sum(r["truncated"] for r in rows)
    if capped:
        print(f"{capped} event(s) across the corpus are truncated; their sizes are not measurements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
