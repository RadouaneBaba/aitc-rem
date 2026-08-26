# Driving this project with Claude Code

Two instruments, one loop, and a short list of things not to automate.

## The loop

```
change something  →  re-run the affected recordings  →  rebuild the packets
                  →  judge  →  fix ONE finding  →  judge again
```

```bash
# 1. what the pipeline produced, assembled into one readable page per recording
.venv/Scripts/python scripts/eval_packet.py

# 2. keep the old output before you change anything -- runs/ is gitignored
.venv/Scripts/python scripts/snapshot_features.py --label "before-<what>"

# 3. ... make the change, re-run the affected recordings ...
.venv/Scripts/python -m server.cli run tests/fixtures/checkout.recording.json --offline

# 4. prove it moved, in the output rather than in a metric
.venv/Scripts/python scripts/snapshot_features.py --label "after-<what>"
.venv/Scripts/python scripts/eval_packet.py
```

Then ask the judge. Verdicts and the running history live in
[`evals/LEDGER.md`](../evals/LEDGER.md).

## The two agents

Both are read-only, and that is the entire reason they exist as agents rather
than as inline work. A judge that can reach the prompt grades its own work.

| | `.claude/agents/qa-judge.md` | `.claude/agents/system-review.md` |
|---|---|---|
| reads | one packet | the whole repo, all findings, STATUS |
| when | after every fix | roughly three times in the project |
| answers | is this test case one a QA lead would sign, and which layer is at fault | is a stage missing, is one obsolete, is a guarantee costing more than it buys |

**Neither edits anything.** You make every change.

Invoke by asking for them by name. The judge follows
[`evals/RUBRIC.md`](../evals/RUBRIC.md), which is deliberately the *complement*
of the fourteen validators — if a validator already checks it, the judge does
not.

### Verify a finding before you act on it

Not a formality. Of the findings spot-checked in the first two passes, two were
wrong, and both were in the judge's top tier:

- a `.feature` and a `.bug.md` reaching "opposite" conclusions — which is
  §14.1's design, not a defect;
- a `narrated` assertion on a fixture with empty narration — which was the
  *packet* omitting a transcript the pipeline attaches at run time.

The second one is the general lesson: **a missing input produces a confident
wrong verdict, not a cautious one.** When a finding surprises you, check the
instrument before you check the code.

## The guardrails

`.claude/settings.json` runs `.claude/hooks/guard.py` before every edit and
shell command. It blocks two things, both of which cost this project real work
once:

- editing `server/models/generated/` or `extension/src/types/` — codegen output;
  edit `schema/*.schema.json` and run `pnpm codegen`;
- `git checkout -- <path>` and `git restore <path>` — no reflog entry, no
  recovery, and large parts of a milestone sit uncommitted here for a long time.

Both fail *open* on an unreadable payload: they prevent mistakes, not attacks,
and one that bricks the session when its input surprises it is worse than none.
Tested in `tests/test_hook_guard.py`, including every `git checkout` that must
still work.

*New agents and hooks are picked up at startup.* If you have just added one,
restart or open `/hooks` — otherwise it silently is not there.

## What not to automate

**Do not put the judge→fix cycle in a `/loop`.** Two failure modes, both
expensive:

- *Quota.* Every re-run after a prompt change is real provider calls against a
  free tier. An unattended loop exhausts the daily allowance in one pass and
  then falls back to stale cassettes — which reads as "no change" rather than
  "it stopped working".
- *Drift with no bottom.* A loop that keeps improving chases ever-smaller
  findings and starts trading one defect for another. This project's own repair
  loop once spent its entire budget making a sentence worse, hedging
  *"submits the payment method"* down to *"clicks Save"*.

`/loop` is for waiting on external state — a CI run, a deploy. Nothing here
waits on anything. Long commands go in the background and notify.

**Do not run the ablation to check a change.** It answers "does agency help",
which is a settled question. Use the packets and the judge.

## When you are done

The definition, which this project did not previously have:

> **Done is a judge pass whose findings are all `architecture` or `tester`** —
> nothing left that a prompt or a rule can fix.

`architecture` findings go to `system-review` and end in
[`DECISIONS.md`](DECISIONS.md). `tester` findings are not code problems at all;
they belong in [`TESTER_ONEPAGER.md`](TESTER_ONEPAGER.md) or in the objective
coach.
