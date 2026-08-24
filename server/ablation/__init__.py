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
    #: SS9.9's convergence rate, as its two counts rather than as a ratio.
    #: `repairConvergenceRate` alone is vacuously 1.0 when the critic found
    #: nothing -- the same trap as `groundingRate` for a configuration that
    #: abstains, met here for the fourth time. A rate is only readable beside
    #: its denominator, so both are columns.
    critic_findings: int = 0
    repairs_resolved: int = 0
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
    def repair_convergence_rate(self) -> float:
        """How often repair fixed the finding within budget (SS9.9).

        Zero, not one, when nothing was found. A configuration with no critic
        did not converge perfectly -- it never diverged, and scoring those the
        same is exactly how `A0` came to look identical to `A2` on grounding
        rate. Read `Converged` with `Findings` beside it or do not read it.
        """
        return self.repairs_resolved / self.critic_findings if self.critic_findings else 0.0

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
            "criticFindings": self.critic_findings,
            "repairsResolved": self.repairs_resolved,
            "repairConvergenceRate": round(self.repair_convergence_rate, 4),
            "toolCalls": self.tool_calls,
            "toolCallsPerStep": round(self.tool_calls_per_step, 3),
            "effortSpread": round(self.effort_spread, 3),
            "replayed": self.replayed,
            "executionRate": round(self.execution_rate, 4),
            "replayAssertions": self.replay_assertions,
            "assertionsHeldRate": round(self.assertions_held_rate, 4),
            "meanSelectorRank": round(self.mean_selector_rank, 3),
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
                ("criticFindings", "Findings", 9),
                ("repairConvergenceRate", "Converged", 10),
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
    """The critic-and-repair comparison, stated whichever way it comes out.

    SS3.5 pre-authorises the null result -- "if A1 is roughly A2, that is a
    genuine finding worth knowing in month two rather than month five" -- so
    this must not be written to make the feature look good. It must also not be
    read on grounding rate alone: A1 and A2 propose assertions with the same
    stage and the same tools, so the rate was never where the difference was
    going to show. What A2 adds is a second opinion on whether the output is any
    good, and the honest columns for that are how many findings it raised and
    how many of them it managed to resolve.
    """
    if not a2.critic_findings:
        return (
            "A2's critic raised no findings at all on this set, so A1 and A2 ran the same "
            "pipeline and their rows should be read as one. That is a result about these "
            "recordings, not about the critic: output the critic has nothing to say about "
            "is output that was already good enough."
        )

    resolved = f"{a2.repairs_resolved} of {a2.critic_findings}"
    unresolved = a2.critic_findings - a2.repairs_resolved
    parts = [
        f"A2's critic raised {a2.critic_findings} finding(s) and the repair loop resolved "
        f"{resolved} within budget ({a2.repair_convergence_rate:.0%})."
    ]
    if unresolved:
        parts.append(
            f"{unresolved} went to the human with the finding stated, which is the designed "
            f"outcome on exhaustion rather than a failure of the loop."
        )
    gap = a2.validator_final_pass - a2.validator_first_pass
    parts.append(
        f"A2's gate went from {a2.validator_first_pass:.0%} on the first attempt to "
        f"{a2.validator_final_pass:.0%} after repair ({gap:+.0%}); A1 has no second "
        f"attempt and sits at {a1.validator_first_pass:.0%}."
    )
    if abs(a1.grounded_yield - a2.grounded_yield) < 0.05:
        parts.append(
            "Yield is within 5 points across the two, which is expected rather than "
            "disappointing: both arms propose assertions with the same stage and the same "
            "tools, so the critic was never going to move it. The columns that separate "
            "them are Findings and Converged."
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
                _replay(metrics, result, recording, replay_parameters or {})
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
    metrics.steps += len(result.naming.steps)
    metrics.assertions += run_metrics.assertionsTotal or 0
    metrics.grounded += run_metrics.assertionsGrounded or 0
    metrics.ungrounded += run_metrics.assertionsUngrounded or 0
    metrics.tool_calls += run_metrics.toolCallsTotal or 0
    metrics.uncached_model_calls += run_metrics.uncachedModelCalls or 0
    metrics.prompt_tokens += run_metrics.promptTokensTotal or 0
    metrics.duration_ms += run_metrics.durationMs or 0.0
    if result.report.hard_failed:
        metrics.hard_failures += 1

    metrics.critic_findings += run_metrics.criticFindingsRaised or 0
    # Counted from the trace rather than derived from the rate, so the row is an
    # aggregate over every finding rather than a mean of per-run ratios -- a run
    # with one finding would otherwise weigh as much as a run with ten.
    metrics.repairs_resolved += len(
        {
            (a.stage, a.targetStepId, a.finding)
            for a in result.trace.repairAttempts
            if a.resolved
        }
    )

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
) -> None:
    """Fill SS3.5's correctness column for one run.

    A blocked replay -- no application listening, a parameter nobody supplied --
    is not counted at all. It is an absence of evidence about the test case, and
    scoring it as a failure would make the column measure the harness.
    """
    from server.runners import replay_all

    try:
        outcomes = replay_all(
            result.ir,
            recording=recording,
            out_dir=result.run.root,
            parameters=parameters,
        )
    except Exception:  # noqa: BLE001 - a broken replay must not lose the run
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
