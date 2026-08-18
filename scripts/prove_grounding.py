#!/usr/bin/env python
"""The agency proof, as a script rather than a diagram (SS3.2).

    "Is it really agentic?" is answered by a script that walks every assertion
    in every output and resolves its pointer. Not a diagram -- a pass/fail
    number.

For each assertion in a run's IR it resolves the cited tool call in the trace,
re-hashes the stored response, and confirms the literal is in it. Then it
reports the numbers that make the claim checkable by someone who does not trust
the pipeline.

    python scripts/prove_grounding.py                 # every run
    python scripts/prove_grounding.py runs/rec_X/run_1
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.models import AgentTrace, IRDocument  # noqa: E402
from server.pipeline.validators.base import contains_literal  # noqa: E402
from server.util.canonical import response_hash  # noqa: E402


@dataclass
class Proof:
    run: Path
    assertions: int = 0
    resolved: int = 0
    tool_calls: int = 0
    problems: list[str] = field(default_factory=list)
    tool_calls_per_step: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems and self.assertions == self.resolved

    @property
    def rate(self) -> float:
        return self.resolved / self.assertions if self.assertions else 1.0


def prove(run: Path) -> Proof | None:
    ir_path, trace_path = run / "ir.json", run / "trace.json"
    if not (ir_path.exists() and trace_path.exists()):
        return None

    proof = Proof(run=run)
    ir = IRDocument.model_validate(json.loads(ir_path.read_text(encoding="utf-8")))
    trace = AgentTrace.model_validate(json.loads(trace_path.read_text(encoding="utf-8")))
    calls = {c.id: c for c in trace.toolCalls}
    proof.tool_calls = len(calls)
    proof.tool_calls_per_step = {i.stepId or i.id: len(i.toolCallIds) for i in trace.investigations}

    for case in ir.testCases:
        for step in case.steps:
            for assertion in step.assertions:
                proof.assertions += 1
                where = f"{case.id}/{step.id}/{assertion.id}"
                call = calls.get(assertion.evidence.toolCallId)

                if call is None:
                    proof.problems.append(
                        f"{where}: cites {assertion.evidence.toolCallId}, not in the trace"
                    )
                    continue

                stored_path = run / call.responsePath
                if not stored_path.exists():
                    proof.problems.append(f"{where}: {call.id} response file is missing")
                    continue

                stored = json.loads(stored_path.read_text(encoding="utf-8"))
                if response_hash(stored) != call.responseHash:
                    proof.problems.append(f"{where}: {call.id} response hash does not verify")
                    continue

                if not contains_literal(stored, assertion.evidence.literal):
                    proof.problems.append(
                        f"{where}: {assertion.evidence.literal!r} is not in {call.id}"
                    )
                    continue

                proof.resolved += 1

    return proof


def main(argv: list[str]) -> int:
    targets = (
        [Path(a) for a in argv[1:]]
        if len(argv) > 1
        else sorted(p.parent for p in (REPO_ROOT / "runs").glob("*/*/trace.json"))
    )
    if not targets:
        print("No runs found. Run the pipeline first.")
        return 0

    proofs = [p for p in (prove(t) for t in targets) if p is not None]
    if not proofs:
        print("No run in those paths has both ir.json and trace.json.")
        return 1

    total_assertions = sum(p.assertions for p in proofs)
    total_resolved = sum(p.resolved for p in proofs)
    total_calls = sum(p.tool_calls for p in proofs)

    for proof in proofs:
        mark = "ok  " if proof.ok else "FAIL"
        print(
            f"[{mark}] {proof.run.relative_to(REPO_ROOT) if proof.run.is_relative_to(REPO_ROOT) else proof.run}"
            f"  {proof.resolved}/{proof.assertions} assertions resolved, "
            f"{proof.tool_calls} tool calls"
        )
        for problem in proof.problems[:10]:
            print(f"         - {problem}")

    print()
    print(f"Runs:            {len(proofs)}")
    print(f"Tool calls:      {total_calls}")
    print(f"Assertions:      {total_assertions}")
    print(f"Resolved:        {total_resolved}")
    rate = total_resolved / total_assertions if total_assertions else 1.0
    print(f"Grounding rate:  {rate:.1%}")

    # The variance in effort per step is what separates an agent from a chain
    # (SS3.4). A chain is flat here by construction.
    spread = {step: n for p in proofs for step, n in p.tool_calls_per_step.items()}
    if spread:
        counts = sorted(spread.values())
        print(
            f"Calls per step:  min {counts[0]}, median {counts[len(counts) // 2]}, "
            f"max {counts[-1]}  ({'varies' if counts[0] != counts[-1] else 'FLAT'})"
        )

    failed = [p for p in proofs if not p.ok]
    print()
    print(
        "PASS: every assertion resolves to a retrieval."
        if not failed
        else f"FAIL: {len(failed)} run(s) contain assertions that do not resolve."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
