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
from server.storage.paths import Storage
from tests.test_pipeline import grounded_model, recording

TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


@pytest.fixture
def client(storage: Storage):
    app = create_app(storage=storage, model_factory=grounded_model)
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


def test_a_failed_job_says_why_rather_than_going_quiet(storage: Storage):
    # A tester who pressed Stop and got silence cannot tell a crash from a slow
    # run, and the second thing they do is press Stop again.
    def broken():
        raise RuntimeError("no model configured")

    app = create_app(storage=storage, model_factory=broken)
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
    step = next(
        s for c in body["ir"]["testCases"] for s in c["steps"] if s["assertions"]
    )
    assertion = step["assertions"][0]

    response = client.patch(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}"
        f"/assertions/{assertion['id']}",
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
    target = next(
        s for c in ir["testCases"] for s in c["steps"] if s["id"] == step["id"]
    )
    target["escalation"] = "did a file download?"
    path.write_text(json.dumps(ir), encoding="utf-8")

    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}/escalation",
        json={"answer": "yes, a CSV downloaded"},
    )
    assert response.status_code == 200, response.text

    edited = next(
        s
        for c in response.json()["ir"]["testCases"]
        for s in c["steps"]
        if s["id"] == step["id"]
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
        e
        for c in response.json()["ir"]["testCases"]
        for s in c["steps"]
        for e in s["eventIds"]
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
        f"/api/runs/{recording_id}/{run_id}/steps/{step['id']}"
        f"/assertions/{assertion['id']}",
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

    response = client.post(
        f"/api/runs/{recording_id}/{run_id}/export", json={"formats": ["xlsx"]}
    )
    assert response.status_code == 200, response.text
    files = response.json()["exports"][0]["files"]
    assert files

    download = client.get(f"/api/runs/{recording_id}/{run_id}/files/{files[0]}")
    assert download.status_code == 200
    assert download.content


def test_a_download_cannot_escape_the_run_directory(client):
    recording_id, run_id = a_run(client)
    response = client.get(
        f"/api/runs/{recording_id}/{run_id}/files/..%2F..%2F..%2Fpyproject.toml"
    )
    assert response.status_code == 404
