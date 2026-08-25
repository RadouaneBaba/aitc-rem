"""The local server (SS13, milestone 13).

    "A local web app. The tester never touches a terminal."

So the test is the whole journey: the recorder posts a recording, a background
job runs the pipeline, and every review action SS13.2 lists is reachable over
HTTP. Driven by a scripted model, because what is under test is the surface a
tester touches, not any model's competence.

The other half is SS13.5: every edit leaves a record. That record is the
`steps edited by a human` column of the ablation and the y-axis of the
effort/difficulty correlation, and it is only free if it happens automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.api.app import create_app
from server.library import StepLibrary
from server.storage.paths import Storage
from tests.test_pipeline import grounded_model, recording

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


@pytest.fixture
def client(storage: Storage, tmp_path: Path):
    # A temporary library, or approving in a test would write into the real
    # project's remembered phrasing (SS12) and quietly change later runs.
    app = create_app(
        storage=storage,
        model_factory=grounded_model,
        library=StepLibrary(tmp_path / "library.db"),
    )
    with TestClient(app) as client:
        client.app.state.storage = storage
        yield client


def post_recording(client) -> dict:
    payload = json.loads(recording().model_dump_json(exclude_none=True))
    response = client.post("/api/recordings", json=payload)
    assert response.status_code == 202, response.text
    body = response.json()
    client.app.state.jobs.wait(30)
    return body


def a_run(client) -> tuple[str, str]:
    post_recording(client)
    runs = client.get("/api/runs").json()["runs"]
    assert runs, "the job produced no run"
    return runs[0]["recordingId"], runs[0]["runId"]


def get_run(client, recording_id: str, run_id: str) -> dict:
    response = client.get(f"/api/runs/{recording_id}/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def first_step(body: dict) -> dict:
    return body["ir"]["testCases"][0]["steps"][0]


# --------------------------------------------------------------------------
# the journey
# --------------------------------------------------------------------------


def test_posting_a_recording_starts_a_job_and_produces_a_run(client):
    body = post_recording(client)

    assert body["job"]["state"] in {"queued", "running", "done"}
    job = client.get(f"/api/jobs/{body['job']['id']}").json()
    assert job["state"] == "done", job
    assert client.get("/api/runs").json()["runs"]


def test_a_failed_job_says_why_rather_than_going_quiet(storage: Storage, tmp_path: Path):
    # A tester who pressed Stop and got silence cannot tell a crash from a slow
    # run, and the second thing they do is press Stop again.
    def broken():
        raise RuntimeError("no model configured")

    app = create_app(
        storage=storage, model_factory=broken, library=StepLibrary(tmp_path / "library.db")
    )
    with TestClient(app) as client:
        payload = json.loads(recording().model_dump_json(exclude_none=True))
        job = client.post("/api/recordings", json=payload).json()["job"]
        client.app.state.jobs.wait(30)

        settled = client.get(f"/api/jobs/{job['id']}").json()
        assert settled["state"] == "failed"
        assert "no model configured" in settled["error"]


def test_a_recording_the_schema_rejects_is_refused_with_a_reason(client):
    response = client.post("/api/recordings", json={"nope": True})
    assert response.status_code == 422
    assert "not a valid recording" in response.text


def test_an_origin_off_the_allowlist_is_reported_to_the_tester(client):
    # SS7.3 -- the pre-send gate, as a fact the UI can show. Reported rather
    # than enforced here: silently dropping the recording would be worse.
    body = post_recording(client)
    assert "unknownOrigins" in body


def test_a_run_carries_everything_the_review_ui_needs(client):
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)

    assert body["ir"]["testCases"]
    assert body["trace"], "the why-this-step panel reads the trace"
    assert body["review"]["approved"] is False
    assert any("Feature:" in text for text in body["feature"].values())


def test_the_evidence_panel_can_fetch_the_retrieval_itself(client):
    # SS13.3 -- the stored tool response, not a summary of it. This is the
    # difference between showing provenance and asserting it.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)

    tool_call_ids = [
        a["evidence"]["toolCallId"]
        for c in body["ir"]["testCases"]
        for s in c["steps"]
        for a in s["assertions"]
    ]
    assert tool_call_ids, "this run grounded nothing, so there is nothing to show"

    response = client.get(f"/api/runs/{recording_id}/{run_id}/tools/{tool_call_ids[0]}")
    assert response.status_code == 200
    assert response.json()


def test_asking_for_a_retrieval_that_was_never_made_is_a_404(client):
    recording_id, run_id = a_run(client)
    assert client.get(f"/api/runs/{recording_id}/{run_id}/tools/tc_9999").status_code == 404


# --------------------------------------------------------------------------
# SS13.2 -- the required interactions
# --------------------------------------------------------------------------


def test_a_step_can_be_reworded_and_the_feature_file_follows(client):
    # A reviewer who edits a step and then downloads a stale .feature has been
    # handed something that does not match what they approved.
    recording_id, run_id = a_run(client)
    step = first_step(get_run(client, recording_id, run_id))

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}",
        json={"text": "the tester submits the purchase order"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert first_step(body)["text"] == "the tester submits the purchase order"
    assert any("submits the purchase order" in t for t in body["feature"].values())


def test_a_step_cannot_be_left_with_no_text(client):
    recording_id, run_id = a_run(client)
    step = first_step(get_run(client, recording_id, run_id))

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}", json={"text": "   "}
    )
    assert response.status_code == 400


def test_rejecting_an_assertion_removes_it_from_the_output(client):
    # The core review loop. Accept/reject is the final gate, and a rejected
    # candidate is not part of the test case.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    step = next(s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"])
    assertion = step["assertions"][0]

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/assertions/{assertion['id']}",
        json={"accepted": False},
    )
    assert response.status_code == 200, response.text
    assert all(assertion["text"] not in t for t in response.json()["feature"].values())


def test_answering_an_escalation_turns_it_into_confirmed_provenance(client):
    # SS13.2 -- the one path where a human states something rather than
    # agreeing with something, which is why it is the only one that may raise
    # provenance.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    step = next(s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"])

    # Put a question on the step the way the naming stage would have.
    path = Path(client.app.state.storage.runs_dir) / recording_id / run_id / "ir.json"
    ir = json.loads(path.read_text(encoding="utf-8"))
    target = next(s for c in ir["testCases"] for s in c["steps"] if s["id"] == step["id"])
    target["escalation"] = "did a file download?"
    path.write_text(json.dumps(ir), encoding="utf-8")

    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/escalation",
        json={"answer": "yes, a CSV downloaded"},
    )
    assert response.status_code == 200, response.text

    edited = next(
        s for c in response.json()["ir"]["testCases"] for s in c["steps"] if s["id"] == step["id"]
    )
    assert "escalation" not in edited or not edited["escalation"]
    assert all(a["provenance"] == "confirmed" for a in edited["assertions"] if a["accepted"])


def test_merging_two_steps_keeps_every_event(client):
    # `event_coverage` must still account for every event after a human edit
    # exactly as it did after the pipeline.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    steps = body["ir"]["testCases"][0]["steps"]
    if len(steps) < 2:
        pytest.skip("this recording produced a single step")

    before = {e for s in steps for e in s["eventIds"]}
    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/steps/merge",
        json={"stepIds": [steps[0]["id"], steps[1]["id"]], "text": "the tester signs in"},
    )
    assert response.status_code == 200, response.text

    after = {
        e for c in response.json()["ir"]["testCases"] for s in c["steps"] for e in s["eventIds"]
    }
    assert after == before


def test_only_adjacent_steps_can_be_merged(client):
    recording_id, run_id = a_run(client)
    steps = get_run(client, recording_id, run_id)["ir"]["testCases"][0]["steps"]
    if len(steps) < 3:
        pytest.skip("this recording is too short to have a gap")

    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/steps/merge",
        json={"stepIds": [steps[0]["id"], steps[2]["id"]]},
    )
    assert response.status_code == 400
    assert "adjacent" in response.text


def test_a_test_case_cannot_be_emptied(client):
    recording_id, run_id = a_run(client)
    steps = get_run(client, recording_id, run_id)["ir"]["testCases"][0]["steps"]

    for step in steps[:-1]:
        client.delete(f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}")

    last = client.delete(f"/api/runs/{recording_id}/{run_id}/steps/{steps[-1]['id']}")
    assert last.status_code == 400


def test_a_case_can_be_renamed(client):
    recording_id, run_id = a_run(client)
    case_id = get_run(client, recording_id, run_id)["ir"]["testCases"][0]["id"]

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/cases/{case_id}",
        json={"title": "Checkout", "scenarioName": "A valid order is confirmed"},
    )
    assert response.status_code == 200
    case = response.json()["ir"]["testCases"][0]
    assert case["title"] == "Checkout"
    assert case["scenarioName"] == "A valid order is confirmed"


# --------------------------------------------------------------------------
# SS13.5 -- the measurement
# --------------------------------------------------------------------------


def test_every_edit_is_recorded_with_its_size(client):
    # Not analytics. This is the ablation's `steps edited by a human` column and
    # SS3.4's y-axis, and it is only affordable because it is automatic.
    recording_id, run_id = a_run(client)
    step = first_step(get_run(client, recording_id, run_id))

    client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}",
        json={"text": "the tester submits the purchase order form"},
    )
    review = get_run(client, recording_id, run_id)["review"]

    assert len(review["edits"]) == 1
    edit = review["edits"][0]
    assert edit["kind"] == "step_text"
    assert edit["stepId"] == step["id"]
    assert edit["magnitude"] > 0, "a rewrite and a typo fix are different signals"


def test_an_edit_that_changes_nothing_is_not_recorded(client):
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    step = next(s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"])
    assertion = step["assertions"][0]

    client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/assertions/{assertion['id']}",
        json={"accepted": assertion["accepted"]},
    )
    assert get_run(client, recording_id, run_id)["review"]["edits"] == []


def test_approval_is_recorded_because_it_is_what_feeds_the_step_library(client):
    # SS12.2 -- a step enters the library because a human accepted it, never
    # because it was generated.
    recording_id, run_id = a_run(client)

    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/approve", json={"reviewer": "radouane"}
    )
    assert response.status_code == 200
    review = response.json()["review"]
    assert review["approved"] is True
    assert review["approvedAt"]
    assert review["reviewer"] == "radouane"


# --------------------------------------------------------------------------
# export, without a terminal
# --------------------------------------------------------------------------


def test_a_reviewer_can_export_and_download_without_a_terminal(client):
    recording_id, run_id = a_run(client)

    response = client.post(f"/api/runs/{recording_id}/{run_id}/export", json={"formats": ["xlsx"]})
    assert response.status_code == 200, response.text
    files = response.json()["exports"][0]["files"]
    assert files

    download = client.get(f"/api/runs/{recording_id}/{run_id}/files/{files[0]}")
    assert download.status_code == 200
    assert download.content


def test_a_download_cannot_escape_the_run_directory(client):
    recording_id, run_id = a_run(client)
    response = client.get(f"/api/runs/{recording_id}/{run_id}/files/..%2F..%2F..%2Fpyproject.toml")
    assert response.status_code == 404


def test_a_reviewer_can_reword_an_expected_result_without_touching_its_evidence(client):
    # Most steps get one candidate, which is correct -- a second invented for a
    # step with one obvious outcome is exactly the weak claim SS9.5 demotes. But
    # that leaves the reviewer a single checkbox, and rejecting it leaves the
    # step with no expected result at all. So the sentence is theirs to fix.
    #
    # The citation is not. `literal` and `toolCallId` are what make the claim
    # admissible (SS3.2), and handing a reviewer the ability to edit them would
    # let anyone turn a guess into a grounded assertion.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    step = next(s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"])
    assertion = step["assertions"][0]

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/assertions/{assertion['id']}",
        json={"text": "the cart shows two items"},
    )
    assert response.status_code == 200, response.text

    after = next(
        a
        for c in response.json()["ir"]["testCases"]
        for s in c["steps"]
        for a in s["assertions"]
        if a["id"] == assertion["id"]
    )
    assert after["text"] == "the cart shows two items"
    assert after["evidence"] == assertion["evidence"]

    edit = next(e for e in response.json()["review"]["edits"] if e["kind"] == "assertion_text")
    assert edit["assertionId"] == assertion["id"]
    assert edit["before"] == assertion["text"]


def test_an_expected_result_cannot_be_reworded_into_nothing(client):
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    step = next(s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"])
    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}"
        f"/assertions/{step['assertions'][0]['id']}",
        json={"text": "   "},
    )
    assert response.status_code == 400


def test_approving_is_what_teaches_the_tool_its_own_vocabulary(client):
    # SS12.2: a step enters the library because a human accepted it, never
    # because it was generated. That is the difference between a vocabulary and
    # a pile of phrasings, and it is also what makes the library the project's
    # memory -- the only thing remembered is work somebody signed off.
    recording_id, run_id = a_run(client)
    library = client.app.state.library
    assert library.entries() == []

    body = get_run(client, recording_id, run_id)
    texts = [s["text"] for c in body["ir"]["testCases"] for s in c["steps"]]

    response = client.post(f"/api/runs/{recording_id}/{run_id}/approve", json={})
    assert response.status_code == 200, response.text

    remembered = {e.text for e in library.entries()}
    assert remembered == set(texts)
    # And it is findable next time by the sentence a model would have drafted.
    assert library.exact(texts[0]) is not None


# --------------------------------------------------------------------------
# narration (SS6.6, SS7.5)
# --------------------------------------------------------------------------


def test_audio_is_posted_before_the_recording_and_kept_beside_it(client, storage):
    """The order is the design, not a convenience.

    `POST /api/recordings` enqueues the pipeline job immediately, so audio that
    arrived afterwards would be transcribed for a run that had already started
    without it -- and the recording.json on disk would then disagree with the
    trace that cites it.
    """
    payload = json.loads(recording().model_dump_json(exclude_none=True))

    audio = client.post(
        f"/api/recordings/{payload['id']}/audio",
        content=b"\x1a\x45\xdf\xa3 not really webm, but bytes on the wire",
        headers={"Content-Type": "audio/webm"},
    )
    assert audio.status_code == 201, audio.text
    assert storage.audio_path(payload["id"]).is_file()

    response = client.post("/api/recordings", json=payload)
    assert response.status_code == 202, response.text
    client.app.state.jobs.wait(30)

    # faster-whisper is an optional extra and these bytes are not real audio, so
    # what is asserted is that the failure is REPORTED. A run that silently
    # dropped narration looks exactly like a tester who did not speak.
    narration = response.json()["narration"]
    assert narration["status"] in {"transcribed", "unavailable"}
    if narration["status"] == "unavailable":
        assert narration["reason"]


def test_a_recording_with_no_audio_says_so_rather_than_failing(client):
    assert post_recording(client)["narration"] == {"status": "none"}


def test_narration_the_tester_supplied_is_not_thrown_away_and_re_guessed(client, storage):
    rec = recording()
    rec.narration = [
        {"id": "nar_001", "startMs": 0, "endMs": 900, "text": "checking the confirmation"}
    ]
    payload = json.loads(rec.model_dump_json(exclude_none=True))
    client.post(
        f"/api/recordings/{payload['id']}/audio",
        content=b"bytes",
        headers={"Content-Type": "audio/webm"},
    )

    body = client.post("/api/recordings", json=payload).json()
    client.app.state.jobs.wait(30)

    assert body["narration"] == {"status": "supplied", "segments": 1}
    # And it survives to disk, so the trace that cites it is reproducible.
    saved = storage.load_recording_json(payload["id"])
    assert saved["narration"][0]["text"] == "checking the confirmation"


def test_the_clip_can_be_played_back_so_a_human_can_check_a_lossy_transcript(client):
    """SS13.3, and the only verification narration can actually have.

    A mis-heard literal passes `evidence_retrieved` and `assertion_grounding`
    both -- the string really is in the response and really is in the index. No
    machine check catches it. A person listening does.
    """
    payload = json.loads(recording().model_dump_json(exclude_none=True))
    client.post(
        f"/api/recordings/{payload['id']}/audio",
        content=b"opus-ish bytes",
        headers={"Content-Type": "audio/webm"},
    )

    played = client.get(f"/api/recordings/{payload['id']}/audio")
    assert played.status_code == 200
    assert played.headers["content-type"] == "audio/webm"
    assert played.content == b"opus-ish bytes"


def test_asking_for_audio_that_was_never_recorded_is_a_404_not_a_crash(client):
    assert client.get("/api/recordings/rec_nothing/audio").status_code == 404


def test_empty_audio_is_refused_rather_than_written_as_a_zero_byte_file(client, storage):
    response = client.post("/api/recordings/rec_x/audio", content=b"")
    assert response.status_code == 400
    assert not storage.audio_path("rec_x").exists()


def test_a_reviewer_can_see_and_hear_what_was_said_during_a_step(client, storage):
    """SS13.3, for the one evidence source a machine cannot re-check.

    The window is the step's events plus the settle tail, and the browser has
    neither event timestamps nor the settle rule -- so it is computed here,
    against the same store the validators read. A reviewer shown a different set
    of segments than the gate considered would be worse than showing none.
    """
    rec = recording()
    rec.narration = [
        {
            "id": "nar_001",
            "startMs": 0,
            "endMs": 500,
            "text": "checking the confirmation appears",
            "confidence": 0.91,
        },
        {
            "id": "nar_002",
            "startMs": 0,
            "endMs": 500,
            "text": "mumbled and half heard",
            "confidence": 0.05,
        },
    ]
    payload = json.loads(rec.model_dump_json(exclude_none=True))
    client.post(
        f"/api/recordings/{payload['id']}/audio",
        content=b"clip",
        headers={"Content-Type": "audio/webm"},
    )
    client.post("/api/recordings", json=payload)
    client.app.state.jobs.wait(30)

    recording_id, run_id = payload["id"], client.get("/api/runs").json()["runs"][0]["runId"]
    body = get_run(client, recording_id, run_id)
    step = body["ir"]["testCases"][0]["steps"][0]

    spoken = client.get(f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/narration").json()
    assert spoken["hasAudio"] is True
    by_id = {s["id"]: s for s in spoken["segments"]}

    # Both are shown. Only one may rank an expected result: a transcription
    # nobody trusts must not outrank an honest inference, and hiding it would
    # leave "the tool ignored what I said" without an answer.
    assert by_id["nar_001"]["supportsRank"] is True
    assert by_id["nar_002"]["supportsRank"] is False


def test_asking_for_narration_on_a_step_that_does_not_exist_is_a_404(client):
    recording_id, run_id = a_run(client)
    response = client.get(f"/api/runs/{recording_id}/{run_id}/steps/step_999/narration")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# editing the feature file directly (SS13.2)
# --------------------------------------------------------------------------


def test_editing_the_feature_text_changes_the_step_it_came_from(client):
    # The tab used to DISPLAY the file, and fixing a sentence meant finding its
    # step in a list and using a form. The reason given was SS13.5's review
    # record -- and a diff between the generated file and the approved one
    # yields exactly the same difficulty labels, so the form was an assumption.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    case_id = body["ir"]["testCases"][0]["id"]
    feature = body["feature"][case_id]

    original = body["ir"]["testCases"][0]["steps"][0]["text"]
    edited = feature.replace(original, "the tester does something else entirely", 1)
    assert edited != feature, "the step text should appear in the rendered file"

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/cases/{case_id}/feature",
        json={"text": edited},
    )
    assert response.status_code == 200, response.text
    after = response.json()

    assert after["ir"]["testCases"][0]["steps"][0]["text"] == (
        "the tester does something else entirely"
    )
    # And it lands in the review record, which is the whole reason every edit
    # goes through `review.py`: SS13.5's log is the project's only source of
    # difficulty labels, and an endpoint that mutated the IR directly would
    # cost that silently.
    kinds = [e["kind"] for e in after["review"]["edits"]]
    assert "step_text" in kinds


def test_editing_an_expected_result_in_the_feature_text_keeps_its_evidence(client):
    # A reviewer may say the same thing better. What they may not do is change
    # `literal` or `toolCallId` -- making an ungrounded claim grounded is not
    # theirs to give (SS3.2), and this path must not become a way round that.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    case = body["ir"]["testCases"][0]
    case_id = case["id"]

    assertion = next(
        (a for s in case["steps"] for a in s["assertions"]),
        None,
    )
    if assertion is None:
        pytest.skip("this run grounded nothing, so there is no expected result to reword")

    feature = body["feature"][case_id]
    edited = feature.replace(assertion["text"], "the order is definitely confirmed", 1)

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/cases/{case_id}/feature",
        json={"text": edited},
    )
    assert response.status_code == 200, response.text
    after = response.json()

    reworded = next(a for s in after["ir"]["testCases"][0]["steps"] for a in s["assertions"])
    assert reworded["text"] == "the order is definitely confirmed"
    assert reworded["evidence"]["literal"] == assertion["evidence"]["literal"]
    assert reworded["evidence"]["toolCallId"] == assertion["evidence"]["toolCallId"]


def test_adding_a_step_by_typing_it_is_refused_with_a_reason(client):
    # A step typed into a text box has no `eventIds`, so it is a sentence about
    # something nobody recorded -- `event_coverage` would reject the run, and
    # rightly. Refusing is the honest answer, and the message has to say what
    # to do instead rather than just "invalid".
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    case_id = body["ir"]["testCases"][0]["id"]

    edited = body["feature"][case_id] + "\n    And the tester does one more thing\n"
    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/cases/{case_id}/feature",
        json={"text": edited},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "number of steps" in detail
    assert "step controls" in detail


def test_saving_the_feature_text_unchanged_records_nothing(client):
    # SS13.5's record is a measurement. An edit logged because somebody opened
    # a tab and pressed Save would put noise into the difficulty labels.
    recording_id, run_id = a_run(client)
    body = get_run(client, recording_id, run_id)
    case_id = body["ir"]["testCases"][0]["id"]
    before = len(body["review"]["edits"])

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/cases/{case_id}/feature",
        json={"text": body["feature"][case_id]},
    )
    assert response.status_code == 200
    assert len(response.json()["review"]["edits"]) == before


# --------------------------------------------------------------------------
# screenshots (SS13.1)
# --------------------------------------------------------------------------

#: The smallest valid PNG. Content does not matter here; what is being tested
#: is that bytes survive the round trip and land where the review UI looks.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "05572bd2b40000000049454e44ae426082"
)


def test_a_screenshot_round_trips_to_where_the_review_ui_looks(client):
    # The recorder has been capturing these since Phase 1 and only the "save to
    # Downloads" path ever kept them, so every posted recording carried a
    # `screenshot` field pointing at a file the server did not have and no
    # reviewer ever saw one.
    posted = client.post("/api/recordings/rec_shots/screens/evt_001", content=PNG)
    assert posted.status_code == 201
    assert posted.json()["bytes"] == len(PNG)

    fetched = client.get("/api/recordings/rec_shots/screens/evt_001")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.content == PNG


def test_a_missing_screenshot_is_a_plain_404(client):
    # An imported recording has none by construction (SS6.1 -- the DevTools
    # Recorder captures no pixels), and a run made before the upload path
    # existed has none either. The UI hides the image rather than showing an
    # error, so this must not be dressed up as a failure.
    assert client.get("/api/recordings/rec_shots/screens/evt_999").status_code == 404


def test_an_event_id_cannot_escape_the_screens_directory(client, tmp_path: Path):
    # The id arrives from an HTTP path and is about to become a filename.
    #
    # Tested at the guard rather than only over HTTP: a client normalises
    # `../..` out of a URL before it reaches the route, so an HTTP-level test
    # passes for a reason that has nothing to do with this code being safe.
    from server.storage.paths import Storage

    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    for bad in ("../../secret", "..", "a/b", "evt 001; rm -rf", ""):
        with pytest.raises(ValueError):
            storage.screenshot_path("rec_x", bad)

    # And the ids the recorder actually mints are accepted.
    assert storage.screenshot_path("rec_x", "evt_001").name == "evt_001.png"

    # Over HTTP, anything that does reach the handler is refused rather than
    # written.
    assert client.post("/api/recordings/rec_shots/screens/a%20b", content=PNG).status_code == 400


def test_an_empty_screenshot_body_is_refused(client):
    assert client.post("/api/recordings/rec_shots/screens/evt_002", content=b"").status_code == 400
