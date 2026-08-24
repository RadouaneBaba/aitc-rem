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
from server.api.review import new_review
from server.config import load_allowed_origins, load_project_config
from server.library import StepLibrary, library_path
from server.llm.cassette import CassetteClient
from server.llm.chain import BudgetGuard, FallbackChain, RateLimiter, RetryingClient
from server.llm.client import ModelClient
from server.llm.gemini import DEFAULT_MODEL, GeminiClient
from server.models import AblationConfig, Recording
from server.pipeline.run import PipelineOptions, run_pipeline
from server.renderers import export_all
from server.renderers.gherkin import trace_filename
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


def check_origins(recording: Recording, *, allow: bool, policy: str = "warn") -> None:
    """The pre-send gate (SS7.3, SS9.12).

    What this guards is a property of the *tier*, not of the provider: free-tier
    prompts are eligible for training and readable by human reviewers, so a
    recording of a real application should not go to one. On a paid endpoint
    carrying a no-training term the question does not arise at all.

    That is why the strength is configurable, and why `warn` is the default.
    Refusing was the wrong shape of gate twice over: the API path in
    `server/api/app.py` has always reported rather than refused, so the two
    entry points disagreed about the same recording; and a tester deliberately
    pointing this at a real site is not doing anything wrong. They need to know
    what it costs, not to be stopped. `allowlist` restores the refusal.
    """
    if policy == "off":
        return

    allowed = load_allowed_origins()
    unknown = [o for o in recording.metadata.origins if o not in allowed]
    if not unknown:
        return

    message = (
        f"This recording touches origins that are not on the allowlist: {', '.join(unknown)}.\n"
        f"Free-tier prompts may be used for training and read by human reviewers, so only\n"
        f"demo and public applications belong there. Add the origin to\n"
        f"config/allowed_origins.yaml, set origin_policy in config/project.yaml, or use a\n"
        f"paid endpoint carrying a no-training term."
    )
    if allow or policy == "warn":
        print(f"WARNING: {message}\n", file=sys.stderr)
        return
    raise SystemExit(f"refusing to send.\n\n{message}")


def cmd_run(args: argparse.Namespace) -> int:
    recording = load_recording(Path(args.recording))
    # House style is project configuration, not a pipeline argument (SS9.12's
    # posture applied to output): it changes how the artifact reads and never
    # what it claims. Loaded before the gate because the gate's strength is one
    # of its settings.
    project = load_project_config()
    check_origins(recording, allow=args.allow_any_origin, policy=project.origin_policy)

    storage = Storage()
    model = build_model(model=args.model, offline=args.offline, rpm=args.rpm)
    options = PipelineOptions.for_config(
        AblationConfig(args.config),
        model_name=args.model,
        budget=args.budget,
        project=project,
        library=StepLibrary(library_path()),
    )

    result = run_pipeline(recording, model, storage=storage, run_id=args.run_id, options=options)

    # An empty review, so this run's effort data has something to join against
    # (SS3.4). "Never reviewed" and "reviewed and nobody changed anything" are
    # different facts, and an absent file conflates them -- the second is the
    # untouched half of the correlation and is the more common half.
    storage.save_artifact(result.run, "review", new_review(result.ir))

    print(f"Recording:      {recording.id}  ({len(recording.events)} events)")
    print(f"Run:            {result.run.root}")
    print(f"Steps:          {len(result.naming.steps)}")
    print(f"Tool calls:     {len(result.trace.toolCalls)}  {result.tool_calls_per_step}")
    print(f"Grounding rate: {result.grounding_rate:.1%}")
    print(f"Duration:       {result.duration_ms / 1000:.1f}s")
    print()
    print(result.report.summary())
    for warning in getattr(model, "warnings", []):
        print(f"\nBUDGET: {warning}")

    exports = export_all(
        result.ir,
        out_dir=result.run.root,
        config=project,
        names=args.export.split(",") if args.export else None,
    )
    for export in exports:
        print(f"Exported:       {export}")
        for warning in export.warnings:
            print(f"                - {warning}")

    if result.rendered:
        print()
        print(next(iter(result.rendered.values())))
    if result.sidecars:
        print(f"Evidence sidecar: {result.run.root / trace_filename(result.ir.testCases[0])}")

    return 0 if result.report.ok else 1


def cmd_ablate(args: argparse.Namespace) -> int:
    recordings = [load_recording(Path(p)) for p in args.recordings]
    policy = load_project_config().origin_policy
    for recording in recordings:
        check_origins(recording, allow=args.allow_any_origin, policy=policy)

    storage = Storage()
    # SS9.12 -- the ablation pins one provider and one model and disables
    # fallback, or it measures provider variance instead of architecture.
    model = build_model(model=args.model, offline=args.offline, fallback=False, rpm=args.rpm)

    report = run_ablation(
        recordings,
        model,
        storage=storage,
        model_name=args.model,
        budget=args.budget,
        replay=args.replay,
        replay_parameters=_replay_parameters(args.replay_param),
    )
    print(report.table())
    print()
    print(report.finding())

    out = Path(args.out)
    write_report(report, out)
    print(f"\nWritten to {out}")
    return 0


def _replay_parameters(pairs: list[str]) -> dict[str, str]:
    """SS7.2's placeholders, supplied for a replay.

    A generated test case genuinely needs them: `<<password>>` is a parameter,
    and a replay that cannot fill it is blocked rather than failed.
    """
    out: dict[str, str] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        if name.strip():
            out[name.strip().strip("<>")] = value
    return out


def cmd_import(args: argparse.Namespace) -> int:
    """Bring a Chrome DevTools Recorder export in as a recording.

    Worth being explicit about what it costs: a DevTools recording carries no
    network calls, no console and no DOM snapshots, so a whole class of
    assertion becomes inadmissible. That is SS3.2 working, not a bug, and the
    run will say so rather than quietly producing fewer expected results.
    """
    from server.importers import import_devtools

    document = json.loads(Path(args.file).read_text(encoding="utf-8"))
    recording = import_devtools(document, recording_id=args.recording_id)

    storage = Storage()
    path = storage.save_recording_json(
        recording.id, json.loads(recording.model_dump_json(exclude_none=True))
    )
    print(f"Imported:  {recording.id}  ({len(recording.events)} events)")
    print(f"Written:   {path}")
    if recording.parameters:
        names = ", ".join(p.placeholder for p in recording.parameters)
        print(f"Redacted:  {names}")
    print()
    print(
        "No network, console or DOM snapshots came with it, so expect fewer expected\n"
        "results than a session recorded with the extension: there is nothing for a\n"
        "claim to cite, so none is made.\n\n"
        "Chrome's Recorder does not redact, so values were redacted HERE rather than in\n"
        "the browser. That is best-effort and pattern-based -- there is no DOM to ask\n"
        "whether a field was a password, only its label. Read the file before sending it\n"
        "anywhere.\n\n"
        "Run it with:\n"
        f"    python -m server.cli run {path}"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """SS13 -- the tester never touches a terminal.

    Except once, here, to start the thing. The extension posts recordings to
    this server, the pipeline runs as a background job, and review happens in a
    browser.
    """
    import uvicorn

    from server.api import create_app

    storage = Storage()
    project = load_project_config()
    options = PipelineOptions.for_config(
        AblationConfig(args.config),
        model_name=args.model,
        budget=args.budget,
        project=project,
        library=StepLibrary(library_path()),
    )
    app = create_app(
        storage=storage,
        model_factory=lambda: build_model(model=args.model, offline=args.offline, rpm=args.rpm),
        options=options,
        config=project,
    )

    ui = REPO_ROOT / "ui" / "dist"
    print(f"aitc-rem on http://{args.host}:{args.port}")
    if not ui.exists():
        print("The review UI is not built yet. Run: pnpm --filter @aitc-rem/ui build")
    print("Point the recorder at this address and press Stop when you are done.")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
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
        help="send even when an origin is not on the allowlist; overrides origin_policy",
    )

    run = sub.add_parser("run", parents=[common], help="run the pipeline over one recording")
    run.add_argument("recording")
    run.add_argument("--config", default="A2", choices=[c.value for c in AblationConfig])
    run.add_argument("--run-id", default="run_001")
    run.add_argument(
        "--export",
        default="",
        help="extra formats, comma separated (xlsx, jira). Overrides config/project.yaml",
    )
    run.set_defaults(func=cmd_run)

    ablate = sub.add_parser("ablate", parents=[common], help="run A0/A1/A2 and print the table")
    ablate.add_argument("recordings", nargs="+")
    ablate.add_argument("--out", default=str(REPO_ROOT / "runs" / "ablation.json"))
    ablate.add_argument(
        "--replay",
        action="store_true",
        help="also drive each generated test case against the demo app (needs `pnpm demo`)",
    )
    ablate.add_argument(
        "--replay-param",
        action="append",
        default=[],
        metavar="name=value",
        help="a value for a redaction placeholder, e.g. --replay-param password=hunter2",
    )
    ablate.set_defaults(func=cmd_ablate)

    imp = sub.add_parser("import", help="bring in a Chrome DevTools Recorder JSON as a recording")
    imp.add_argument("file")
    imp.add_argument("--recording-id", default=None)
    imp.set_defaults(func=cmd_import)

    serve = sub.add_parser("serve", parents=[common], help="run the local server and the review UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--config", default="A2", choices=[c.value for c in AblationConfig])
    serve.set_defaults(func=cmd_serve)

    # Read .env before anything asks for a key, so the CLI works without the
    # caller having exported it into their shell.
    load_env()

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
