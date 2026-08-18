"""Command line entry points for the Phase 1 spine.

    python -m server.cli run <recording.json> [--config A2] [--offline]
    python -m server.cli ablate <recording.json>... [--out runs/ablation.json]

Model wiring lives here rather than in the pipeline: SS9.12 keeps provider and
model as configuration, and the pipeline only ever sees a `ModelClient`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from server.ablation import run_ablation, write_report
from server.llm.cassette import CassetteClient
from server.llm.chain import BudgetGuard, FallbackChain, RateLimiter, RetryingClient
from server.llm.client import ModelClient
from server.llm.gemini import DEFAULT_MODEL, GeminiClient
from server.models import AblationConfig, Recording
from server.pipeline.run import PipelineOptions, run_pipeline
from server.storage.paths import REPO_ROOT, Storage
from server.util.env import load_env

CASSETTES = REPO_ROOT / "runs" / "_cassettes"
BUDGET_STATE = REPO_ROOT / "runs" / "_budget.json"


def build_model(
    *,
    model: str,
    offline: bool,
    fallback: bool = True,
    daily_limit: int = 200,
    rpm: int = 5,
) -> ModelClient:
    """The decorator stack, outermost last.

        budget( cassette( pace( chain( retry( gemini ) ) ) ) )

    Order matters, and getting it wrong is silent:

    * Retry sits INSIDE the chain, wrapping each provider. Outside it, the
      chain converts a RateLimited into AllProvidersExhausted before retry ever
      sees it, so a limit that would clear in seconds ends the run instead.
      Each provider now waits out its own transient limits, and the chain
      fails over only when one is genuinely finished.
    * The cassette sits OUTSIDE the pacer and the chain, so a replay neither
      waits for a rate-limit slot nor reaches a provider. That is what makes
      re-running after a validator change effectively free.
    * It sits INSIDE the budget guard, so replays are not counted against the
      daily allowance.
    """
    providers = [RetryingClient(GeminiClient(model=model))]
    chain = FallbackChain(providers, enabled=fallback)
    paced = RateLimiter(chain, requests_per_minute=rpm)
    cassettes = CassetteClient(paced, CASSETTES, mode="read_only" if offline else "read_write")
    return BudgetGuard(cassettes, BUDGET_STATE, daily_limit=daily_limit)


def load_recording(path: Path) -> Recording:
    return Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))


def check_origins(recording: Recording, *, allow: bool) -> None:
    """The pre-send gate (SS7.3, SS9.12).

    Free-tier prompts are eligible for training and human review, so a
    recording of a real application must not be sent to one. The allowlist
    makes that a mechanical check rather than a note in a document.
    """
    config_path = REPO_ROOT / "config" / "allowed_origins.yaml"
    allowed: list[str] = []
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("- "):
                allowed.append(line[2:].strip().strip("\"'"))

    unknown = [o for o in recording.metadata.origins if o not in allowed]
    if not unknown:
        return

    message = (
        f"This recording touches origins that are not on the allowlist: {', '.join(unknown)}.\n"
        f"Free-tier prompts may be used for training and read by human reviewers, so only\n"
        f"demo and public applications belong there. Add the origin to\n"
        f"config/allowed_origins.yaml, or pass --allow-any-origin if this endpoint carries a\n"
        f"no-training term."
    )
    if allow:
        print(f"WARNING: {message}\n", file=sys.stderr)
        return
    raise SystemExit(f"refusing to send.\n\n{message}")


def cmd_run(args: argparse.Namespace) -> int:
    recording = load_recording(Path(args.recording))
    check_origins(recording, allow=args.allow_any_origin)

    storage = Storage()
    model = build_model(model=args.model, offline=args.offline, rpm=args.rpm)
    options = PipelineOptions.for_config(
        AblationConfig(args.config), model_name=args.model, budget=args.budget
    )

    result = run_pipeline(recording, model, storage=storage, run_id=args.run_id, options=options)

    print(f"Recording:      {recording.id}  ({len(recording.events)} events)")
    print(f"Run:            {result.run.root}")
    print(f"Steps:          {len(result.naming.steps)}")
    print(f"Tool calls:     {len(result.trace.toolCalls)}  {result.naming.tool_calls_per_step()}")
    print(f"Grounding rate: {result.grounding_rate:.1%}")
    print(f"Duration:       {result.duration_ms / 1000:.1f}s")
    print()
    print(result.report.summary())
    for warning in getattr(model, "warnings", []):
        print(f"\nBUDGET: {warning}")

    if result.rendered:
        print()
        print(next(iter(result.rendered.values())))

    return 0 if result.report.ok else 1


def cmd_ablate(args: argparse.Namespace) -> int:
    recordings = [load_recording(Path(p)) for p in args.recordings]
    for recording in recordings:
        check_origins(recording, allow=args.allow_any_origin)

    storage = Storage()
    # SS9.12 -- the ablation pins one provider and one model and disables
    # fallback, or it measures provider variance instead of architecture.
    model = build_model(model=args.model, offline=args.offline, fallback=False, rpm=args.rpm)

    report = run_ablation(
        recordings, model, storage=storage, model_name=args.model, budget=args.budget
    )
    print(report.table())
    print()
    print(report.finding())

    out = Path(args.out)
    write_report(report, out)
    print(f"\nWritten to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aitc-rem")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=DEFAULT_MODEL)
    common.add_argument("--budget", type=int, default=8, help="tool calls per step")
    common.add_argument(
        "--rpm",
        type=int,
        default=5,
        help="pace to this many requests per minute (Gemini free tier allows 5; 0 disables)",
    )
    common.add_argument(
        "--offline",
        action="store_true",
        help="replay from cassettes only; fail rather than calling a provider",
    )
    common.add_argument(
        "--allow-any-origin",
        action="store_true",
        help="send even when an origin is not on the allowlist (paid, no-training endpoints)",
    )

    run = sub.add_parser("run", parents=[common], help="run the pipeline over one recording")
    run.add_argument("recording")
    run.add_argument("--config", default="A2", choices=[c.value for c in AblationConfig])
    run.add_argument("--run-id", default="run_001")
    run.set_defaults(func=cmd_run)

    ablate = sub.add_parser("ablate", parents=[common], help="run A0/A1/A2 and print the table")
    ablate.add_argument("recordings", nargs="+")
    ablate.add_argument("--out", default=str(REPO_ROOT / "runs" / "ablation.json"))
    ablate.set_defaults(func=cmd_ablate)

    # Read .env before anything asks for a key, so the CLI works without the
    # caller having exported it into their shell.
    load_env()

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
