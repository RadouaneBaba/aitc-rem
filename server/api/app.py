"""The local server (SS13, SS9.11).

    "A local web app. The tester never touches a terminal."

That sentence is the whole point of this file. The recorder posts here when the
tester presses Stop, the pipeline runs as a background job, and the browser
opens on a draft. Nobody types a path to a `recording.json`.

Local-only by construction: no auth, no tenancy, no billing (SS16 -- none of
them are one-way doors, and all of them slow the MVP). What *is* carried from
day one is `projectId`, `ownerId` and `createdAt`, so becoming multi-user later
is a deployment change rather than a migration.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from server.api import review as review_ops
from server.api.jobs import Job, JobRunner
from server.config import (
    ProjectConfig,
    load_allowed_origins,
    load_project_config,
    normalise_origin,
)
from server.models import (
    ExpectationSet,
    ExpectationSource,
    IRDocument,
    PipelineStage,
    Recording,
    ReviewDocument,
)
from server.pipeline.run import PipelineOptions, run_pipeline
from server.renderers import export_all
from server.renderers.gherkin import feature_filename, render_document, trace_filename
from server.renderers.trace_md import render_document as render_sidecars
from server.storage.paths import REPO_ROOT, Storage

UI_DIST = REPO_ROOT / "ui" / "dist"

#: What each pipeline stage is called for someone watching a browser tab. A run
#: takes minutes on purpose (SS9.11), but "deliberately slow" and "hung" look
#: identical without this, and the second thing a tester does is press Stop
#: again. Prose rather than stage names: the reader is a QA tester, not a
#: developer reading a trace.
STAGE_DETAIL = {
    PipelineStage.segment: "reading the recording",
    PipelineStage.expectations: "working out what should have happened",
    PipelineStage.author: "writing the test cases",
    PipelineStage.render: "writing the feature file",
    PipelineStage.validate: "checking every claim against the evidence",
    PipelineStage.judge: "reading it back as a QA lead would",
    PipelineStage.coverage: "looking for what this session did not cover",
}


class ExpectationAnswer(BaseModel):
    """One card on the confirmation screen, answered."""

    id: str
    source: ExpectationSource
    #: Only read for `corrected`. See `post_expectations`.
    expected: str | None = None
    note: str | None = None


class ExpectationAnswers(BaseModel):
    answers: list[ExpectationAnswer] = []


class RecordingPayload(BaseModel):
    """What the extension posts. Validated as a `Recording` immediately after."""

    model_config = {"extra": "allow"}


class TextEdit(BaseModel):
    text: str


class AssertionEdit(BaseModel):
    """Accept or reject an expected result, or reword one.

    `text` never carries `literal` or `toolCallId`: a reviewer may say the same
    thing better, and may not make an ungrounded claim grounded (SS3.2).
    """

    accepted: bool | None = None
    text: str | None = None


class EscalationAnswer(BaseModel):
    answer: str


class MergeRequest(BaseModel):
    stepIds: list[str]
    text: str | None = None


class MoveRequest(BaseModel):
    toCaseId: str
    position: int = 0


class RenameRequest(BaseModel):
    title: str | None = None
    scenarioName: str | None = None


class ApproveRequest(BaseModel):
    reviewer: str | None = None


class ExportRequest(BaseModel):
    formats: list[str] = []


def create_app(
    *,
    storage: Storage | None = None,
    model_factory=None,
    options: PipelineOptions | None = None,
    config: ProjectConfig | None = None,
) -> FastAPI:
    """Build the app.

    `model_factory` is injected rather than imported so the tests can drive the
    whole surface with a scripted model and no API key.
    """
    storage = storage or Storage()
    config = config or load_project_config()
    runner = JobRunner()

    app = FastAPI(title="aitc-rem", version="0.1.0")
    app.state.storage = storage
    app.state.config = config
    app.state.jobs = runner

    # The recorder runs inside whatever page the tester is on, so the POST is
    # cross-origin by definition. Local-only server, local-only exposure.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _model():
        if model_factory is not None:
            return model_factory()
        from server.cli import build_model

        return build_model(model=(options or PipelineOptions()).model_name, offline=False)

    # -- recordings ------------------------------------------------------

    @app.post("/api/recordings", status_code=202)
    def post_recording(payload: RecordingPayload) -> dict[str, Any]:
        """The extension's Stop button lands here."""
        raw = payload.model_dump()
        try:
            recording = Recording.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - reported to the recorder
            raise HTTPException(422, f"not a valid recording: {exc}") from exc

        unknown = _unknown_origins(recording, config.origin_policy)

        # SS6.6 -- narration, if the recorder captured any. The audio arrives on
        # its own endpoint BEFORE this one, because this call enqueues the job
        # immediately and transcription has to have something to read.
        #
        # It happens here rather than inside `_run` so that what is saved to
        # disk is the recording the pipeline actually saw. A recording.json
        # whose narration existed only in memory would make every trace
        # referencing it unreproducible.
        transcription = _transcribe_if_audio(recording, storage, config)
        storage.save_recording(recording)

        run_id = _next_run_id(storage, recording.id)
        job = runner.enqueue(
            recording.id,
            lambda job: _run(job, recording, storage, _model(), options, config),
            run_id=run_id,
        )
        return {
            "job": job.as_dict(),
            # SS7.3 -- the pre-send screen, as a fact the UI can show rather
            # than a promise in a document.
            "unknownOrigins": unknown,
            "narration": transcription,
        }

    @app.get("/api/recordings/{recording_id}/expectations")
    def get_expectations(recording_id: str) -> dict[str, Any]:
        """What the pipeline thinks should have happened, for the tester to check.

        404 while the guess is still running, which is the normal first second
        after Stop: the confirmation screen polls the job and then asks here.
        """
        stored = storage.load_expectations(recording_id)
        if stored is None:
            raise HTTPException(404, f"no expectations for {recording_id} yet")
        return stored

    @app.post("/api/recordings/{recording_id}/expectations")
    def post_expectations(recording_id: str, payload: ExpectationAnswers) -> dict[str, Any]:
        """The confirmation screen, coming back.

        This is the most valuable interaction in the product and the cheapest:
        the tester reads a guess and presses one of three buttons. Everything
        the pipeline can otherwise know is a restatement of what the application
        DID; this is the only place anybody says what it SHOULD have done.

        Answering enqueues a fresh run, because the answers are an INPUT to
        authoring rather than an edit to its output. The first run has already
        happened by now on the guesses alone -- a run must never wait for a
        screen somebody might not open -- so this produces a better second
        draft beside it rather than unblocking a first one.
        """
        stored = storage.load_expectations(recording_id)
        if stored is None:
            raise HTTPException(404, f"no expectations for {recording_id}")

        expectations = ExpectationSet.model_validate(stored)
        by_id = {e.id: e for e in expectations.expectations}
        unknown = [a.id for a in payload.answers if a.id not in by_id]
        if unknown:
            raise HTTPException(422, f"no such expectation(s): {', '.join(unknown)}")

        for answer in payload.answers:
            target = by_id[answer.id]
            target.source = answer.source
            # Only a rewrite replaces the sentence. A tick means "your guess was
            # right", and overwriting the guess with itself would lose nothing
            # but reads as an edit in the diff.
            if answer.expected and answer.source == ExpectationSource.corrected:
                target.expected = answer.expected
            if answer.note:
                target.note = answer.note

        expectations.confirmedAt = datetime.now(UTC)
        storage.save_expectations(expectations)

        recording = Recording.model_validate(storage.load_recording_json(recording_id))
        run_id = _next_run_id(storage, recording_id)
        job = runner.enqueue(
            recording_id,
            lambda job: _run(
                job,
                recording,
                storage,
                _model(),
                _with_expectations(options, expectations),
                config,
            ),
            run_id=run_id,
        )
        return {"job": job.as_dict(), "expectations": expectations.model_dump(mode="json", exclude_none=True)}

    @app.post("/api/recordings/{recording_id}/audio", status_code=201)
    async def post_audio(recording_id: str, request: Request) -> dict[str, Any]:
        """Narration audio, posted before the recording it belongs to (SS7.5).

        A raw body rather than multipart: there is exactly one file, the
        recorder already knows its own id, and multipart would buy a parser
        dependency and a form-field name in exchange for nothing.

        The audio does not leave this machine. This server is `127.0.0.1`, the
        transcription runs in-process, and the pipeline only ever sees text.
        """
        data = await request.body()
        if not data:
            raise HTTPException(400, "empty audio body")
        path = storage.save_audio(recording_id, data)
        return {"bytes": len(data), "path": str(path)}

    @app.get("/api/recordings/{recording_id}/audio")
    def get_audio(recording_id: str):
        """SS13.3 -- so a reviewer can hear what was actually said.

        The only verification a lossy evidence source can have. A mis-heard
        literal passes every grounding check this project makes, so the check
        that matters is a person listening.
        """
        path = storage.audio_path(recording_id)
        if not path.is_file():
            raise HTTPException(404, "this recording has no narration audio")
        return FileResponse(path, media_type="audio/webm", filename=path.name)

    @app.post("/api/recordings/{recording_id}/screens/{event_id}", status_code=201)
    async def post_screenshot(recording_id: str, event_id: str, request: Request):
        """One event's screenshot, posted after the recording (SS13.1).

        The recorder has been taking these since Phase 1 and only the "save to
        Downloads" path ever kept them, so every posted recording carried a
        `screenshot` field pointing at a file this server did not have and no
        reviewer ever saw one. They are the cheapest large improvement
        available to the review UI: a step is much easier to judge beside the
        page it happened on.

        Deliberately after the recording rather than before it, which is the
        opposite of the audio ordering. Audio has to arrive first because
        transcription feeds the run; a screenshot feeds nothing but a human, so
        it must not delay the job.
        """
        data = await request.body()
        if not data:
            raise HTTPException(400, "empty screenshot body")
        try:
            path = storage.save_screenshot(recording_id, event_id, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"bytes": len(data), "path": str(path)}

    @app.get("/api/recordings/{recording_id}/screens/{event_id}")
    def get_screenshot(recording_id: str, event_id: str):
        try:
            path = storage.screenshot_path(recording_id, event_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not path.is_file():
            raise HTTPException(404, "no screenshot for this event")
        return FileResponse(path, media_type="image/png", filename=path.name)

    @app.get("/api/recordings")
    def list_recordings() -> dict[str, Any]:
        return {"recordings": storage.list_recordings()}

    @app.get("/api/expectations/pending")
    def pending_expectations() -> dict[str, Any]:
        """Recordings whose guesses nobody has answered yet.

        The oracle is the thing the whole rebuild rests on, and it was
        unreachable in practice. The confirmation screen opened only on
        `?confirm=<id>`, read once at mount, linked from exactly one place --
        the extension's export page -- and dismissed for good. Miss that link
        and there is no route back. The result, measured: **14 expectation sets
        on disk and all 14 still `inferred`**, so every downstream stage has
        only ever read unconfirmed guesses, and A1-vs-A2 -- what asking a human
        is worth -- has never been measurable.

        `confirmedAt` already exists in the schema for exactly this question;
        its own description says distinguishing "never asked" from "asked and
        agreed" is the whole point of storing it. Nothing had ever read it.

        This does not make the run wait. `POST /api/recordings` still guesses,
        runs and produces a draft on the guesses alone, and answering enqueues a
        SECOND run -- the skip path is the one that has to be right, because it
        is what happens by default.
        """
        out: list[dict[str, Any]] = []
        for recording_id in storage.list_recordings():
            stored = storage.load_expectations(recording_id)
            if not stored or stored.get("confirmedAt"):
                continue
            items = stored.get("expectations") or []
            if not items:
                # Nothing to confirm is not the same as nothing to do: a
                # recording the guesser found no action worth asking about
                # should not sit on the dashboard forever.
                continue
            out.append(
                {
                    "recordingId": recording_id,
                    "count": len(items),
                    "createdAt": stored.get("createdAt"),
                }
            )
        out.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
        return {"pending": out}

    # -- jobs ------------------------------------------------------------

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [j.as_dict() for j in runner.all()]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = runner.status(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return job.as_dict()

    # -- runs ------------------------------------------------------------

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": _list_runs(storage)}

    @app.get("/api/runs/{recording_id}/{run_id}")
    def get_run(recording_id: str, run_id: str) -> dict[str, Any]:
        run = storage.existing_run(recording_id, run_id)
        ir = _load_ir(run.root)
        return {
            "ir": ir.model_dump(mode="json", exclude_none=True),
            "trace": _load_json(run.root / "trace.json"),
            "review": _load_review(run.root, ir).model_dump(mode="json", exclude_none=True),
            "feature": _feature_text(run.root, ir, config),
            "screens": _screens(storage, recording_id),
        }

    @app.get("/api/runs/{recording_id}/{run_id}/steps/{step_id}/narration")
    def step_narration(recording_id: str, run_id: str, step_id: str) -> dict[str, Any]:
        """What the tester said during this step, and whether it counted.

        Computed here rather than matched in the browser because the window is
        the step's events plus its settle tail, and the UI has neither event
        timestamps nor the settle rule. Reuses the store the validators read, so
        a reviewer cannot be shown a different set of segments than the ones the
        gate considered.
        """
        from server.evidence.store import EvidenceStore
        from server.pipeline.transcribe import supports_narrated

        run = storage.existing_run(recording_id, run_id)
        ir = _load_ir(run.root)
        step = next(
            (s for case in ir.testCases for s in case.steps if s.id == step_id),
            None,
        )
        if step is None:
            raise HTTPException(404, f"no step {step_id} in this run")

        # The recording itself is not part of a run, and a run outlives it:
        # `runs/` is kept for the ablation while `recordings/` gets cleared, so
        # most runs on disk have no recording beside them. This endpoint used
        # to call `load_recording_json` straight into a `.read_text()`, so
        # opening any such run threw `FileNotFoundError` -- a 500 on first
        # paint and again on every step click. The panel `.catch`es it and
        # shows nothing, which is why the app still works and the terminal
        # fills with tracebacks. There is simply no narration to report.
        if not storage.recording_path(recording_id).is_file():
            return {"segments": [], "hasAudio": storage.audio_path(recording_id).is_file()}

        recording = Recording.model_validate(storage.load_recording_json(recording_id))
        store = EvidenceStore(recording=recording)
        times = [store.event(e).timestamp for e in step.eventIds if store.has_event(e)]
        if not times:
            return {"segments": [], "hasAudio": storage.audio_path(recording_id).is_file()}

        segments = store.narration(min(times), max(times) + 2000)
        return {
            "hasAudio": storage.audio_path(recording_id).is_file(),
            "minConfidence": config.narration_min_confidence,
            "segments": [
                {
                    **s.model_dump(mode="json", exclude_none=True),
                    # Stated rather than left for the UI to recompute: the gate
                    # and the panel disagreeing about which sentence counted
                    # would be worse than not showing it at all.
                    "supportsRank": supports_narrated(s, config.narration_min_confidence),
                }
                for s in segments
            ],
        }

    @app.get("/api/runs/{recording_id}/{run_id}/tools/{tool_call_id}")
    def get_tool_response(recording_id: str, run_id: str, tool_call_id: str) -> Any:
        """SS13.3's evidence panel: the retrieval itself, not a summary of it."""
        run = storage.existing_run(recording_id, run_id)
        path = run.tool_response(tool_call_id)
        if not path.exists():
            raise HTTPException(404, f"no stored response for {tool_call_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    # -- review ----------------------------------------------------------

    def _edit(recording_id: str, run_id: str, mutate) -> dict[str, Any]:
        run = storage.existing_run(recording_id, run_id)
        ir = _load_ir(run.root)
        review = _load_review(run.root, ir)
        try:
            mutate(ir, review)
        except review_ops.ReviewError as exc:
            raise HTTPException(400, str(exc)) from exc

        review_ops.resync_keywords(ir)
        _save(run.root, ir, review, config)
        return {
            "ir": ir.model_dump(mode="json", exclude_none=True),
            "review": review.model_dump(mode="json", exclude_none=True),
            "feature": _feature_text(run.root, ir, config),
        }

    @app.patch("/api/runs/{recording_id}/{run_id}/steps/{step_id}")
    def patch_step(recording_id: str, run_id: str, step_id: str, body: TextEdit):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.edit_step_text(ir, rv, step_id=step_id, text=body.text),
        )

    @app.delete("/api/runs/{recording_id}/{run_id}/steps/{step_id}")
    def remove_step(recording_id: str, run_id: str, step_id: str):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.delete_step(ir, rv, step_id=step_id),
        )

    @app.patch("/api/runs/{recording_id}/{run_id}/steps/{step_id}/assertions/{assertion_id}")
    def patch_assertion(
        recording_id: str, run_id: str, step_id: str, assertion_id: str, body: AssertionEdit
    ):
        # Two edits on one route because they are one thought for the reviewer:
        # this expected result is right, or it is right once reworded. The
        # citation is not editable from here at all (SS3.2).
        if body.text is not None:
            return _edit(
                recording_id,
                run_id,
                lambda ir, rv: review_ops.edit_assertion_text(
                    ir, rv, step_id=step_id, assertion_id=assertion_id, text=body.text or ""
                ),
            )
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.set_assertion(
                ir, rv, step_id=step_id, assertion_id=assertion_id, accepted=bool(body.accepted)
            ),
        )

    @app.post("/api/runs/{recording_id}/{run_id}/steps/{step_id}/escalation")
    def resolve_escalation(recording_id: str, run_id: str, step_id: str, body: EscalationAnswer):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.answer_escalation(
                ir, rv, step_id=step_id, answer=body.answer
            ),
        )

    @app.post("/api/runs/{recording_id}/{run_id}/steps/merge")
    def merge(recording_id: str, run_id: str, body: MergeRequest):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.merge_steps(ir, rv, step_ids=body.stepIds, text=body.text),
        )

    @app.post("/api/runs/{recording_id}/{run_id}/steps/{step_id}/move")
    def move(recording_id: str, run_id: str, step_id: str, body: MoveRequest):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.move_step(
                ir, rv, step_id=step_id, to_case_id=body.toCaseId, position=body.position
            ),
        )

    @app.patch("/api/runs/{recording_id}/{run_id}/cases/{case_id}")
    def rename(recording_id: str, run_id: str, case_id: str, body: RenameRequest):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.rename_case(
                ir, rv, case_id=case_id, title=body.title, scenario_name=body.scenarioName
            ),
        )

    @app.patch("/api/runs/{recording_id}/{run_id}/cases/{case_id}/feature")
    def patch_feature(recording_id: str, run_id: str, case_id: str, body: TextEdit):
        """Edit the feature file directly (SS13.2).

        The tab used to display it and every edit had to go through a
        step-shaped form. The reason given for that was SS13.5's review record,
        and it does not hold: a diff between the generated file and the
        approved one yields exactly the same difficulty labels the forms do.

        So the text is editable and the changes are replayed through the same
        review functions the forms call -- the record is identical either way,
        and nothing writes to the IR behind its back.
        """
        run = storage.existing_run(recording_id, run_id)
        rendered = _feature_text(run.root, _load_ir(run.root), config).get(case_id, "")
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.apply_feature_text(
                ir, rv, case_id=case_id, text=body.text, rendered=rendered
            ),
        )

    @app.post("/api/runs/{recording_id}/{run_id}/approve")
    def approve(recording_id: str, run_id: str, body: ApproveRequest):
        return _edit(
            recording_id,
            run_id,
            lambda ir, rv: review_ops.approve(ir, rv, reviewer=body.reviewer),
        )

    @app.post("/api/runs/{recording_id}/{run_id}/export")
    def export(recording_id: str, run_id: str, body: ExportRequest) -> dict[str, Any]:
        run = storage.existing_run(recording_id, run_id)
        ir = _load_ir(run.root)

        # `no_placeholder_leak` is the only validator whose action is
        # `hard_fail`, and the pipeline responds by erasing the `.feature`, the
        # sidecar and the bug report. The IR survives -- that validator scans
        # `case.model_dump()`, so the leaked value is inside it by definition --
        # and every exporter reads a finished IRDocument. Exporting here would
        # write the secret into an xlsx or a Jira issue through the one path
        # SS7.1 exists to make impossible. The CLI gates this too; this endpoint
        # had no check at all.
        if _hard_failed(run.root):
            raise HTTPException(
                409,
                "this run hard-failed on redaction, and every export reads the same IR. "
                "Fix the recording and run it again.",
            )

        results = export_all(ir, out_dir=run.root, config=config, names=body.formats or None)
        return {
            "exports": [
                {
                    "exporter": r.exporter,
                    "files": [p.name for p in r.files],
                    "warnings": r.warnings,
                }
                for r in results
            ]
        }

    @app.get("/api/runs/{recording_id}/{run_id}/files/{name}")
    def download(recording_id: str, run_id: str, name: str):
        """Approve then export, without a terminal (SS13.2)."""
        run = storage.existing_run(recording_id, run_id)
        path = (run.root / name).resolve()
        if not path.is_file() or run.root.resolve() not in path.parents:
            raise HTTPException(404, f"no file {name} in this run")
        return FileResponse(path, filename=path.name)

    # -- the app itself --------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "ui": UI_DIST.exists()}

    if UI_DIST.exists():
        # A catch-all rather than `StaticFiles(html=True)` mounted at "/".
        #
        # The UI has real routes now -- `/confirm/<id>` and `/help` -- and a
        # static mount answers 404 for both, because there is no such file. A
        # link somebody pastes or a page they reload would land on nothing,
        # which is precisely the failure the router exists to fix: the
        # confirmation screen was unreachable, and shipping it behind a URL the
        # server refuses to serve would leave it unreachable in a new way.
        #
        # Registered LAST, so every `/api/...` route above wins on match order.
        @app.get("/{path:path}")
        def ui(path: str) -> Response:
            # An unmatched `/api/...` path is a 404 and must never be answered
            # with the app shell. The catch-all sits below every real API route,
            # so anything still reaching here under `/api` is a request nothing
            # serves -- and returning 200 with HTML to a client expecting JSON
            # turns "no such endpoint" into a parse error three layers away.
            # It also silently un-did the download path-traversal guard, which
            # is how this was noticed.
            if path.startswith("api/"):
                raise HTTPException(404, f"no such endpoint: /{path}")
            candidate = (UI_DIST / path).resolve()
            if path and UI_DIST.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(UI_DIST / "index.html")
    else:

        @app.get("/")
        def no_ui() -> JSONResponse:
            return JSONResponse(
                {
                    "error": "the review UI has not been built",
                    "fix": "pnpm --filter @aitc-rem/ui build",
                },
                status_code=503,
            )

    return app


# --------------------------------------------------------------------------


def _run(
    job: Job,
    recording: Recording,
    storage: Storage,
    model,
    options: PipelineOptions | None,
    config: ProjectConfig,
) -> dict[str, Any]:
    opts = options or PipelineOptions()
    opts.project = config

    def progress(stage: PipelineStage) -> None:
        job.detail = STAGE_DETAIL.get(stage, stage.value)

    opts.on_stage = progress

    job.detail = STAGE_DETAIL[PipelineStage.segment]
    result = run_pipeline(
        recording, model, storage=storage, run_id=job.run_id or "run_001", options=opts
    )

    review = review_ops.new_review(result.ir)
    storage.save_artifact(result.run, "review", review)

    job.detail = (
        "ready for review" if result.report.ok else "ready for review, with validator findings"
    )
    return {
        "runId": result.run.run_id,
        "groundingRate": result.grounding_rate,
        "ok": result.report.ok,
    }


def _with_expectations(
    options: PipelineOptions | None, expectations: ExpectationSet
) -> PipelineOptions:
    """A copy carrying the tester's answers, never a mutation of the shared one.

    `options` is the app's, reused by every request. Setting the oracle on it
    would leak one recording's expectations into the next recording's run --
    which would be silent, and would look exactly like the model guessing well.
    """
    base = options or PipelineOptions()
    return replace(base, expectations=expectations)


def _unknown_origins(recording: Recording, policy: str = "warn") -> list[str]:
    """SS7.3 -- what would leave the browser, and whether it is allowed to.

    Reported rather than enforced: a UI that silently dropped a recording would
    be worse than one that shows the tester exactly which origin is the problem.
    The CLI now agrees, rather than refusing where this reports (SS7.3's gate is
    "one-time per project, not per recording"), and both read `origin_policy`.

    `off` means a paid, no-training endpoint, where there is nothing to report.
    """
    if policy == "off":
        return []
    allowed = set(load_allowed_origins())
    return [o for o in recording.metadata.origins if normalise_origin(o) not in allowed]


def _transcribe_if_audio(
    recording: Recording, storage: Storage, config: ProjectConfig
) -> dict[str, Any]:
    """Narration audio -> `recording.narration`, locally (SS6.6).

    Degrades loudly, and the return value is what makes that possible: a run
    that silently dropped the narration is indistinguishable from a tester who
    did not speak, and the output would be quietly worse for a reason nothing on
    screen explains. So the reason travels back to the export page, which is
    still open and is the last place the tester is looking.

    Narration already on the recording wins. A tester who corrected a transcript
    and re-sent it should not have it thrown away and re-guessed.
    """
    if recording.narration:
        return {"status": "supplied", "segments": len(recording.narration)}

    audio = storage.audio_path(recording.id)
    if not audio.is_file():
        return {"status": "none"}

    from server.pipeline.transcribe import (
        TranscriptionSettings,
        TranscriptionUnavailable,
        transcribe,
    )

    try:
        recording.narration = transcribe(
            audio,
            settings=TranscriptionSettings(
                model=config.narration_model,
                language=config.narration_language,
                min_confidence=config.narration_min_confidence,
            ),
            offset_ms=recording.metadata.audioOffsetMs or 0.0,
        )
    except TranscriptionUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}

    if not config.narration_keep_audio:
        audio.unlink(missing_ok=True)

    return {
        "status": "transcribed",
        "segments": len(recording.narration),
        "model": config.narration_model,
        # Below the threshold a segment is kept and readable but cannot support
        # the `narrated` rank. Surfaced rather than hidden: "the tool ignored
        # what I said" needs an answer, and this is it.
        "unsure": sum(
            1
            for s in recording.narration
            if s.confidence is not None and s.confidence < config.narration_min_confidence
        ),
    }


def _next_run_id(storage: Storage, recording_id: str) -> str:
    root = storage.runs_dir / recording_id
    existing = [p.name for p in root.iterdir() if p.is_dir()] if root.exists() else []
    return f"run_{len(existing) + 1:03d}"


def _list_runs(storage: Storage) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not storage.runs_dir.exists():
        return out

    for ir_path in sorted(storage.runs_dir.glob("*/*/ir.json")):
        try:
            ir = IRDocument.model_validate(json.loads(ir_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a half-written run must not hide the rest
            continue
        review = _load_review(ir_path.parent, ir)
        # Enough for a reviewer to decide which run to open next, without
        # opening any of them. A dropdown of ids answers "which runs exist";
        # a tester with fifteen recordings needs "which of these needs me",
        # and the answer is in `ir.json` already.
        warnings = sum(len(c.warnings) for c in ir.testCases)
        # `whyNot` rather than `criticNotes`: the critic is deleted, and its
        # replacement hands findings to the AUTHOR and never to the tester. What
        # needs a person here is a step the author could not find a verdict for
        # and said so about -- which is the one thing on this screen only a
        # human can close.
        flagged = sum(
            1 for c in ir.testCases for s in c.steps if s.whyNot or s.criticNotes or s.escalation
        )
        out.append(
            {
                "recordingId": ir.recordingId,
                "runId": ir.runId,
                "createdAt": ir.createdAt.isoformat(),
                "approved": review.approved,
                "titles": [c.title for c in ir.testCases],
                "scenarios": [c.scenarioName or c.title for c in ir.testCases],
                "steps": sum(len(c.steps) for c in ir.testCases),
                "assertions": sum(len(s.assertions) for c in ir.testCases for s in c.steps),
                "warnings": warnings,
                "flaggedSteps": flagged,
                # SS13.5's record, read back as progress. `edits` is
                # append-only, so the distinct steps touched is the honest
                # count of "how far through this has somebody got".
                "editedSteps": len({e.stepId for e in review.edits if e.stepId}),
                "hasBug": any(c.kind == "bug_report" for c in ir.testCases),
            }
        )
    return sorted(out, key=lambda r: r["createdAt"], reverse=True)


def _load_ir(root: Path) -> IRDocument:
    path = root / "ir.json"
    if not path.exists():
        raise HTTPException(404, "this run has no ir.json yet")
    return IRDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_review(root: Path, ir: IRDocument) -> ReviewDocument:
    path = root / "review.json"
    if path.exists():
        return ReviewDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return review_ops.new_review(ir)


def _screens(storage: Storage, recording_id: str) -> list[str]:
    """Which events have a picture, told once instead of asked per step.

    The reviewer's step pane rendered an `<img>` for every step and hid it
    `onError`, so a recording with no `screens/` directory -- an import, or any
    run whose recording was cleared -- produced one 404 per step click. The
    browser logs those whatever the handler does, which is most of the noise on
    the console. Nothing is broken by a missing picture (SS7.4: it is for the
    human and never leaves the machine), so the fix is to stop asking.
    """
    folder = storage.recordings_dir / recording_id / "screens"
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.png"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _hard_failed(root: Path) -> bool:
    """Did the gate refuse to write this run's output at all?

    Read from `trace.json`, which is where the gate's verdict is persisted --
    `validatorResults` carries every row with its action, and `hard_fail` is
    reachable by exactly one validator (`no_placeholder_leak`). A run with no
    trace has not been through the gate, and is not treated as clean.
    """
    trace = _load_json(root / "trace.json")
    if not trace:
        return True
    return any(
        str(row.get("action")) == "hard_fail" for row in trace.get("validatorResults") or []
    )


def _feature_text(root: Path, ir: IRDocument, config: ProjectConfig) -> dict[str, str]:
    return render_document(ir, config=config)


def _save(root: Path, ir: IRDocument, review: ReviewDocument, config: ProjectConfig) -> None:
    """Re-render on every edit.

    The feature file and the IR are the same artifact in two forms, and a
    reviewer who edits a step and then downloads a stale `.feature` has been
    handed something that does not match what they approved.
    """
    review.updatedAt = datetime.now(UTC)
    (root / "ir.json").write_text(
        json.dumps(ir.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "review.json").write_text(
        json.dumps(review.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for case_id, text in render_document(ir, config=config).items():
        case = next(c for c in ir.testCases if c.id == case_id)
        (root / feature_filename(case, config)).write_text(text, encoding="utf-8")

    if config.trace == "sidecar":
        trace = _load_json(root / "trace.json")
        agent_trace = None
        if trace:
            from server.models import AgentTrace

            agent_trace = AgentTrace.model_validate(trace)
        for case_id, text in render_sidecars(ir, trace=agent_trace, config=config).items():
            case = next(c for c in ir.testCases if c.id == case_id)
            (root / trace_filename(case, config)).write_text(text, encoding="utf-8")


__all__ = ["create_app"]
