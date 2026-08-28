"""The ablation harness (SS3.5) -- the thesis deliverable.

    "Three pipeline configurations, one flag, the same recordings."

    A0  single prompt, all context pre-loaded, no tools -- the shape this
        project replaces
    A1  tools available, no critic, no repair loop
    A2  full pipeline

Six of the seven metrics come from machinery built for other reasons, which is
why this is a config flag and a script rather than an eval harness, and why it
lands in Phase 1 rather than at the end.

Two constraints from SS9.12 are enforced rather than left to discipline: one
provider and one model are pinned across all three configurations, and fallback
routing is disabled. Routing is fine in daily use and fatal here, because the
comparison would otherwise measure provider variance instead of architecture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.llm.client import ModelClient
from server.models import AblationConfig, Recording
from server.pipeline.run import PipelineOptions, PipelineResult, run_pipeline
from server.storage.paths import Storage

CONFIGS = [AblationConfig.A0, AblationConfig.A1, AblationConfig.A2]


@dataclass
class ConfigMetrics:
    """One row of the SS3.5 table, for one configuration."""

    config: str
    recordings: int = 0
    steps: int = 0
    assertions: int = 0
    grounded: int = 0
    ungrounded: int = 0
    validator_first_pass: float = 0.0
    #: The same gate after the repair loop finished. Read as a pair with the
    #: first-attempt rate: the distance between them is what repair bought, and
    #: a single number reporting only the second would be the repair loop
    #: marking its own homework.
    validator_final_pass: float = 0.0
    #: What the judge said about the document that SHIPPED, as counts and
    #: deliberately not as a ratio. `repairConvergenceRate` was vacuously 1.0
    #: when the critic found nothing -- the same trap as `groundingRate` for a
    #: configuration that abstains, met there for the fourth time and six times
    #: now in total. `judge_fails` non-zero means a run went out carrying
    #: something a QA lead would send back, which is exactly what a rate hides.
    judge_findings: int = 0
    judge_fails: int = 0
    #: Author rounds, summed. Equal to `recordings` means nothing was ever
    #: revised; anything above it is the loop firing.
    revision_rounds: int = 0
    #: Findings handed back to the author, one per (round, finding). A different
    #: fact from `judge_findings` -- a rejected claim is a repair with no judge
    #: finding behind it -- and the two were the same number here until it
    #: turned out that number was neither of them.
    repair_attempts: int = 0
    tool_calls: int = 0
    tool_calls_per_step: float = 0.0
    #: Steps whose tool-call count differs from the run's mean. A chain is flat
    #: here by construction, so any spread at all separates the architectures.
    #:
    #: Counts INVESTIGATION only. `tool_calls_per_step` above is total cost and
    #: includes the search-before-invent call SS12.2 mandates on every step;
    #: this excludes it, because a call the process requires regardless of
    #: difficulty is a constant, and adding a constant to every reading makes an
    #: adaptive agent look like a chain. See `run._calls_per_step`.
    effort_spread: float = 0.0
    #: SS3.5's missing column. Grounding proves a claim points at a retrieval;
    #: it says nothing about whether the test would run. Counted only over cases
    #: a replay actually attempted -- "could not run" is not evidence.
    replayed: int = 0
    replays_passed: int = 0
    #: Accepted assertions that were re-checked in a browser, and how many still
    #: held. `execution_rate` on its own is vacuous in exactly the way
    #: `grounding_rate` is -- a test case that asserts nothing cannot have an
    #: assertion fail -- so the two are always read together.
    replay_assertions: int = 0
    replay_assertions_held: int = 0
    selector_rank_total: float = 0.0
    #: Why a replay could not be attempted, when it could not. An empty
    #: `replayed` count reads identically whether nothing was tried or
    #: everything threw, and those are different facts about the run.
    replay_errors: list[str] = field(default_factory=list)
    uncached_model_calls: int = 0
    prompt_tokens: int = 0
    duration_ms: float = 0.0
    hard_failures: int = 0

    @property
    def grounding_rate(self) -> float:
        """Share of claims that were licensed by a retrieval.

        Vacuously 1.0 when nothing was claimed, which is why it is never read
        on its own: a configuration that abstains scores the same as one that
        grounds everything. `grounded_yield` is what separates them.
        """
        return self.grounded / self.assertions if self.assertions else 1.0

    @property
    def execution_rate(self) -> float:
        """Share of replayed test cases that ran green.

        Read beside `grounding_rate`, not instead of it: a configuration that
        asserts nothing executes perfectly, for the same reason it grounds
        perfectly.
        """
        return self.replays_passed / self.replayed if self.replayed else 0.0

    @property
    def assertions_held_rate(self) -> float:
        """Of the accepted expected results a browser could re-check, how many
        were still true. This is the column that separates a test case that
        works from one that merely has nothing to say."""
        return (
            self.replay_assertions_held / self.replay_assertions if self.replay_assertions else 0.0
        )

    @property
    def mean_selector_rank(self) -> float:
        """How far down the fallback chain a replay had to go, on average.

        0 means the most stable selector always worked. The demo app has no
        `data-testid` anywhere, so this measures the role+name path that is the
        normal case for an application nobody built for testing.
        """
        return self.selector_rank_total / self.replayed if self.replayed else 0.0

    @property
    def grounded_yield(self) -> float:
        """Grounded assertions per step -- how much usable output was produced.

        This is the column that distinguishes the three configurations when the
        model is well behaved. Without tools there is no id to cite, so an
        honest model omits the expected result entirely: it fabricates nothing
        and produces nothing, and only yield shows that.
        """
        return self.grounded / self.steps if self.steps else 0.0

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "config": self.config,
            "recordings": self.recordings,
            "steps": self.steps,
            "assertions": self.assertions,
            "grounded": self.grounded,
            "ungrounded": self.ungrounded,
            "groundingRate": round(self.grounding_rate, 4),
            "groundedYield": round(self.grounded_yield, 4),
            "validatorFirstPassRate": round(self.validator_first_pass, 4),
            "validatorFinalPassRate": round(self.validator_final_pass, 4),
            "judgeFindings": self.judge_findings,
            "judgeFails": self.judge_fails,
            "revisionRounds": self.revision_rounds,
            "repairAttempts": self.repair_attempts,
            "toolCalls": self.tool_calls,
            "toolCallsPerStep": round(self.tool_calls_per_step, 3),
            "effortSpread": round(self.effort_spread, 3),
            "replayed": self.replayed,
            "executionRate": round(self.execution_rate, 4),
            "replayAssertions": self.replay_assertions,
            "assertionsHeldRate": round(self.assertions_held_rate, 4),
            "meanSelectorRank": round(self.mean_selector_rank, 3),
            "replayErrors": list(self.replay_errors),
            "uncachedModelCalls": self.uncached_model_calls,
            "promptTokens": self.prompt_tokens,
            "durationMs": round(self.duration_ms, 1),
            "hardFailures": self.hard_failures,
        }


@dataclass
class AblationReport:
    rows: dict[str, ConfigMetrics] = field(default_factory=dict)
    runs: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"table": [m.as_dict() for m in self.rows.values()], "runs": self.runs}

    #: Two blocks rather than one row, because the row is 15 columns wide and it
    #: goes on a page. They are grouped by the question they answer: what the
    #: run CLAIMED, and what it DID to get there. `as_dict` and the JSON report
    #: are unaffected -- this is presentation only.
    BLOCKS = (
        (
            "What it claimed",
            [
                ("config", "Config", 6),
                ("assertions", "Assert", 7),
                ("groundingRate", "Grounded", 9),
                ("groundedYield", "Yield", 7),
                ("ungrounded", "Fabric.", 8),
                ("validatorFirstPassRate", "Valid1st", 9),
                ("validatorFinalPassRate", "ValidFin", 9),
            ],
        ),
        (
            "What it did to get there",
            [
                ("config", "Config", 6),
                ("toolCallsPerStep", "Calls/step", 11),
                ("effortSpread", "Spread", 7),
                ("judgeFindings", "Judged", 7),
                ("judgeFails", "Unsigned", 9),
                ("revisionRounds", "Rounds", 7),
                ("executionRate", "Executes", 9),
                ("replayAssertions", "Rechecked", 10),
                ("assertionsHeldRate", "Held", 6),
                ("promptTokens", "PromptTok", 10),
            ],
        ),
    )

    def table(self) -> str:
        """The SS3.5 table, as text. Deliberately plain: it goes in a thesis."""
        rows = [m.as_dict() for m in self.rows.values()]
        out: list[str] = []
        for title, columns in self.BLOCKS:
            header = "  ".join(name.rjust(width) for _, name, width in columns)
            if out:
                out.append("")
            out.append(title)
            out.append(header)
            out.append("-" * len(header))
            for data in rows:
                out.append("  ".join(str(data[key]).rjust(width) for key, _, width in columns))
        return "\n".join(out)

    def finding(self) -> str:
        """A0 vs A2 in one sentence, stated whichever way it comes out.

        SS3.5: "if A1 is roughly A2, that is a genuine finding worth knowing in
        month two rather than month five."
        """
        a0 = self.rows.get("A0")
        a1 = self.rows.get("A1")
        a2 = self.rows.get("A2")
        if not (a0 and a2):
            return "incomplete: A0 and A2 are both needed for a comparison"

        parts = [
            f"A0 produced {a0.grounded} grounded assertion(s) across {a0.steps} step(s) "
            f"({a0.grounded_yield:.2f} per step); A2 produced {a2.grounded} across "
            f"{a2.steps} ({a2.grounded_yield:.2f} per step)."
        ]
        if a0.assertions and a0.ungrounded == a0.assertions:
            parts.append(
                "Every A0 assertion was ungrounded, which is what SS3.2 predicts: with no "
                "tools there is no retrieval to cite, so a claim is either omitted or invented."
            )
        elif a0.assertions == 0:
            parts.append(
                "A0 emitted no assertions at all -- it declined to claim rather than "
                "fabricating, which is the honest failure mode and the reason grounding RATE "
                "must not be read alone: abstaining scores 100% on rate and zero on yield."
            )
        if a1 and a2:
            parts.append(_a1_vs_a2(a1, a2))
        return " ".join(parts)


def _a1_vs_a2(a1: ConfigMetrics, a2: ConfigMetrics) -> str:
    """What the ORACLE was worth, stated whichever way it comes out.

    The arms were redefined with the rebuild and this paragraph with them. A1
    and A2 used to differ by "critic and repair loop", and comparing those
    measured a loop that resolved one finding in nine. They now differ by
    whether anybody said what SHOULD have happened -- which is the measurement
    this project has never been able to make, because until the oracle existed
    there was nothing to compare against.

    SS3.5 pre-authorises the null result -- "if A1 is roughly A2, that is a
    genuine finding worth knowing in month two rather than month five" -- so
    this must not be written to make the feature look good. Grounding rate is
    the wrong place to look for the difference: both arms retrieve with the same
    stage and the same tools, so the rate was never going to move. The oracle
    changes WHAT gets asserted, not whether the assertion can be traced, and the
    columns that show that are Yield and the judge's.
    """
    parts: list[str] = []

    yield_gap = a2.grounded_yield - a1.grounded_yield
    if abs(yield_gap) < 0.05:
        parts.append(
            f"Yield is within 5 points across the two ({a1.grounded_yield:.2f} against "
            f"{a2.grounded_yield:.2f}), so on this set being told what should have happened "
            f"did not change how much the author was willing to claim."
        )
    else:
        direction = "more" if yield_gap > 0 else "less"
        parts.append(
            f"A2 produced {direction} grounded output per step than A1 "
            f"({a1.grounded_yield:.2f} -> {a2.grounded_yield:.2f}, {yield_gap:+.2f}), which is "
            f"what the oracle is for: it changes what is worth asserting."
        )

    if not (a1.judge_findings or a2.judge_findings):
        parts.append(
            "The judge had nothing to say about either arm. That is a result about these "
            "recordings rather than about the judge -- output nobody objects to is output "
            "that was already good enough -- and it is only readable because the count is "
            "printed rather than a convergence rate over it."
        )
    else:
        parts.append(
            f"The judge raised {a1.judge_findings} finding(s) against A1 and "
            f"{a2.judge_findings} against A2, of which {a1.judge_fails} and {a2.judge_fails} "
            f"respectively still stood on the document that shipped."
        )
        if a2.judge_fails:
            parts.append(
                f"{a2.judge_fails} went out with the finding recorded, which is the designed "
                f"outcome on exhaustion rather than a failure of the loop."
            )

    revised = a2.revision_rounds - a2.recordings
    parts.append(
        f"A2 revised {revised} time(s) across {a2.recordings} recording(s); a document is "
        f"rewritten at most once, and never merely because a finding was weak."
    )
    return " ".join(parts)


def run_ablation(
    recordings: list[Recording],
    model: ModelClient,
    *,
    storage: Storage,
    model_name: str,
    configs: list[AblationConfig] | None = None,
    budget: int = 8,
    run_prefix: str = "abl",
    replay: bool = False,
    replay_parameters: dict[str, str] | None = None,
    replay_base_url: str | None = None,
    replay_storage_state: Path | None = None,
) -> AblationReport:
    """Run every configuration over every recording.

    `replay` additionally drives each generated test case against the demo app
    and fills the `Executes` column. Off by default: it needs the application
    running, and an ablation that silently depends on a live server is one
    nobody else can reproduce.
    """
    report = AblationReport()

    for config in configs or CONFIGS:
        metrics = ConfigMetrics(config=config.value)
        for recording in recordings:
            options = PipelineOptions.for_config(
                config,
                model_name=model_name,
                budget=budget,
                # Pinned: see the module docstring.
                fallback_enabled=False,
            )
            result = run_pipeline(
                recording,
                model,
                storage=storage,
                run_id=f"{run_prefix}_{config.value}_{recording.id}",
                options=options,
            )
            if replay:
                _replay(
                    metrics,
                    result,
                    recording,
                    replay_parameters or {},
                    replay_base_url,
                    replay_storage_state,
                )
            _accumulate(metrics, result)
            report.runs.append(
                {
                    "config": config.value,
                    "recordingId": recording.id,
                    "runId": result.trace.runId,
                    "runPath": str(result.run.root),
                }
            )
        report.rows[config.value] = metrics

    return report


def _accumulate(metrics: ConfigMetrics, result: PipelineResult) -> None:
    run_metrics = result.trace.metrics
    assert run_metrics is not None

    metrics.recordings += 1
    metrics.steps += len(result.document.steps)
    metrics.assertions += run_metrics.assertionsTotal or 0
    metrics.grounded += run_metrics.assertionsGrounded or 0
    metrics.ungrounded += run_metrics.assertionsUngrounded or 0
    metrics.tool_calls += run_metrics.toolCallsTotal or 0
    metrics.uncached_model_calls += run_metrics.uncachedModelCalls or 0
    metrics.prompt_tokens += run_metrics.promptTokensTotal or 0
    metrics.duration_ms += run_metrics.durationMs or 0.0
    if result.report.hard_failed:
        metrics.hard_failures += 1

    # Summed over findings rather than averaged over runs, so a run with one
    # finding does not weigh as much as a run with ten.
    #
    # Not a rate, and that is the decision rather than an omission. `Converged`
    # answered 1-of-9 while measuring how much of what the critic said the loop
    # was ALLOWED to act on, and this project has met that trap in six columns.
    # `Unsigned` is what the judge still objected to on the document that
    # SHIPPED -- a count, of a thing that is either true of the artifact or not.
    metrics.judge_findings += run_metrics.judgeFindings or 0
    metrics.judge_fails += run_metrics.judgeFails or 0
    metrics.revision_rounds += run_metrics.revisionRounds or 0
    metrics.repair_attempts += run_metrics.repairAttempts or 0

    # Running means, so the row stays correct across a growing recording set.
    n = metrics.recordings
    metrics.validator_first_pass += (
        (run_metrics.validatorFirstPassRate or 0.0) - metrics.validator_first_pass
    ) / n
    metrics.validator_final_pass += (
        (run_metrics.validatorFinalPassRate or 0.0) - metrics.validator_final_pass
    ) / n

    per_step = list((run_metrics.toolCallsPerStep or {}).values())
    metrics.tool_calls_per_step = metrics.tool_calls / metrics.steps if metrics.steps else 0.0
    if per_step:
        mean = sum(per_step) / len(per_step)
        spread = (sum((v - mean) ** 2 for v in per_step) / len(per_step)) ** 0.5
        metrics.effort_spread += (spread - metrics.effort_spread) / n


def _replay(
    metrics: ConfigMetrics,
    result: Any,
    recording: Recording,
    parameters: dict[str, str],
    base_url: str | None = None,
    storage_state: Path | None = None,
) -> None:
    """Fill SS3.5's correctness column for one run.

    A blocked replay -- no application listening, a parameter nobody supplied --
    is not counted at all. It is an absence of evidence about the test case, and
    scoring it as a failure would make the column measure the harness.
    """
    from server.runners import DEFAULT_BASE_URL, replay_all

    try:
        outcomes = replay_all(
            result.ir,
            recording=recording,
            out_dir=result.run.root,
            base_url=base_url or DEFAULT_BASE_URL,
            parameters=parameters,
            storage_state=storage_state,
        )
    except Exception as exc:  # noqa: BLE001 - a broken replay must not lose the run
        # Losing the run to a replay failure would be worse; losing the FACT of
        # the failure is how `Executes: 0.0` stayed unexamined for a year while
        # reading as a measurement. The run survives and says what happened.
        metrics.replay_errors.append(f"{type(exc).__name__}: {exc}")
        return

    for outcome in outcomes:
        if outcome.blocked or not outcome.ran:
            continue
        metrics.replayed += 1
        metrics.replays_passed += 1 if outcome.passed else 0
        metrics.replay_assertions += outcome.assertions_checked
        metrics.replay_assertions_held += outcome.assertions_held
        metrics.selector_rank_total += outcome.mean_selector_rank


def write_report(report: AblationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.as_dict()
    payload["finding"] = report.finding()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


__all__ = [
    "CONFIGS",
    "AblationReport",
    "ConfigMetrics",
    "run_ablation",
    "write_report",
]
