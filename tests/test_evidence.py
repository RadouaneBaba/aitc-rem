"""The evidence store and the logging that turns retrieval into evidence.

SS8 -- "the contract is not a format, it is queryability". These tests check
that the recording really is queryable, and that every query leaves behind the
content-addressed record `evidence_retrieved` will later resolve.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.evidence.store import EvidenceStore
from server.evidence.tools import TOOLS, ToolRunner
from server.models import PipelineStage, Recording
from server.pipeline.segment import segment_recording
from server.storage.paths import Storage
from server.util.canonical import response_hash
from tests import factories as f

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def store() -> EvidenceStore:
    events = [
        f.event("evt_001", 0, at=0.0, etype="input", tgt=f.target("textbox", "Email address")),
        f.event(
            "evt_002",
            1,
            at=500.0,
            diff=f.confirmation_diff(),
            network=[f.network_call(status=201)],
            after=f.snapshot(
                root=f.node(
                    "0",
                    "main",
                    "Checkout",
                    children=[f.node("0.0", "button", "Place order")],
                ),
                live=[f.node("live.0", "alert", "Order confirmed")],
            ),
        ),
        f.event("evt_003", 2, at=900.0, tgt=f.target("button", "Print receipt")),
    ]
    recording = f.recording(events=events, objective="verify the order confirmation")
    st = EvidenceStore(recording=recording)
    st.attach_segments(segment_recording(recording, run_id="run_test"))
    return st


@pytest.fixture
def runner(store: EvidenceStore, tmp_path: Path) -> ToolRunner:
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    return ToolRunner(
        store=store,
        storage=storage,
        run=storage.run(store.recording.id, "run_test"),
        stage=PipelineStage.author,
    )


# --------------------------------------------------------------------------
# the store answers questions
# --------------------------------------------------------------------------


def test_events_are_reachable_by_id(store: EvidenceStore):
    assert store.event("evt_002").timestamp == 500.0
    assert store.has_event("evt_002")
    assert not store.has_event("evt_999")


def test_an_unknown_event_says_what_it_does_have(store: EvidenceStore):
    # The message goes back to the agent verbatim, so it has to be actionable.
    with pytest.raises(KeyError) as excinfo:
        store.event("evt_999")
    assert "evt_001..evt_003" in str(excinfo.value)


def test_find_text_locates_the_string_an_assertion_would_quote(store: EvidenceStore):
    matches = store.find_text("Order confirmed")
    assert matches
    assert matches[0]["kind"] == "semantic_node"
    assert matches[0]["eventId"] == "evt_002"


def test_find_text_is_case_insensitive_by_default(store: EvidenceStore):
    assert store.find_text("order CONFIRMED")
    assert not store.find_text("order CONFIRMED", case_sensitive=True)


def test_find_text_searches_network_and_console_too(store: EvidenceStore):
    matches = store.find_text("/api/orders")
    assert any(m["kind"] == "network" for m in matches)


def test_find_text_searches_the_page_url(store: EvidenceStore):
    # SS9.5 counts a meaningful URL change as an outcome signal, and the IR has
    # a `url` evidence kind for exactly that. Neither was reachable while the
    # index covered nodes, requests, console and narration but not the page the
    # tester was on: a URL assertion passed `evidence_retrieved` because the
    # string really was in the tool response, then failed `assertion_grounding`
    # because the recording could not be searched where the URL lives. Both
    # validators were right; the index was incomplete.
    matches = store.find_text("demo.local/checkout")

    assert any(m["kind"] == "url" for m in matches)
    assert all(m.get("eventId") for m in matches if m["kind"] == "url")


def test_a_url_assertion_can_be_grounded_at_the_event_it_belongs_to(store: EvidenceStore):
    # The property `assertion_grounding` actually checks: the literal appears
    # in the recording AT the cited event, not merely somewhere in it.
    matches = [m for m in store.find_text("demo.local/checkout") if m["kind"] == "url"]
    assert {m["eventId"] for m in matches} <= {e.id for e in store.recording.events}


def test_find_text_reports_nothing_for_a_string_that_was_never_there(store: EvidenceStore):
    # This is the case that stops fabrication: the agent asks, and is told no.
    assert store.find_text("Payment declined") == []


def _long_recording(repeats: int) -> EvidenceStore:
    """A session where the same string appears at every event.

    `MAX_MATCHES` is 40 and matches sort by a zero-padded event id, so any
    recording with more than 40 hits pushes its LATEST events off the end of
    `find_text` -- and the latest events are where a test's verdict lives.
    """
    events = [
        f.event(
            f"evt_{index:03d}",
            index,
            at=float(index * 100),
            after=f.snapshot(
                root=f.node("0", "main", "Hampers"),
                live=[f.node("live.0", "status", "Large Wicker Basket")],
            ),
        )
        for index in range(repeats)
    ]
    return EvidenceStore(recording=f.recording(events=events, objective="fill the hamper"))


def test_a_presence_check_is_not_capped_at_forty_matches():
    # The failure this fixes, measured on `rec_MT7MXBS9B2VB`: 'Wicker Basket'
    # was at evt_032, `find_text` returned 40 matches ending at evt_009, and
    # `assertion_grounding` rejected a true, correctly cited claim as
    # ungrounded. Both the validator and the binder were right; the index they
    # were reading stopped partway through the session.
    store = _long_recording(50)
    last = f"evt_{49:03d}"

    capped = store.find_text("Large Wicker Basket", case_sensitive=True)
    assert len(capped) == 40, "the agent-facing tool still bounds its response"
    assert not any(m.get("eventId") == last for m in capped), "the cap drops the newest events"

    assert store.contains_at("Large Wicker Basket", last, case_sensitive=True)
    assert last in store.events_containing("Large Wicker Basket", case_sensitive=True)


def test_a_presence_check_still_says_no_to_a_string_that_was_never_there():
    # The negative case. Uncapping must not turn the index into something that
    # says yes: refusing is the behaviour that stops fabrication.
    store = _long_recording(50)
    assert not store.contains_at("Payment declined", "evt_049")
    assert store.events_containing("Payment declined") == []


def test_a_scoped_search_is_scoped_in_every_source(store: EvidenceStore):
    # `scope` was honoured by the semantic-node loop alone, so a scoped search
    # still returned every URL, request, console line and annotation in the
    # session. A per-event search that answers about other events is not a
    # per-event search, and `contains_at` is built on this.
    everywhere = store.find_text("/api/orders")
    assert everywhere, "the string is in the recording"

    for match in store.find_text("/api/orders", scope="evt_001"):
        assert match.get("eventId") == "evt_001"


def test_query_element_returns_the_node_and_its_neighbours(store: EvidenceStore):
    result = store.query_element("evt_002", role="alert")
    assert result["found"]
    assert result["matches"][0]["name"] == "Order confirmed"
    assert result["neighbours"]


def test_query_element_needs_something_to_match_on(store: EvidenceStore):
    with pytest.raises(ValueError):
        store.query_element("evt_002")


def test_narration_is_empty_but_answerable(store: EvidenceStore):
    assert store.narration(0, 10_000) == []


def test_neighbouring_segments_give_surrounding_context(store: EvidenceStore):
    first = store.segments.segments[0].id
    assert store.neighbouring_segments(first, 1)


# --------------------------------------------------------------------------
# every call is logged, hashed and addressable
# --------------------------------------------------------------------------


def test_a_call_writes_a_hashed_content_addressed_response(runner: ToolRunner):
    call_id, response = runner.call("get_snapshot", {"eventId": "evt_002"})

    assert call_id == "tc_0001"
    record = runner.calls[0]
    assert record.tool == "get_snapshot"
    assert record.stage == PipelineStage.author

    # The stored bytes must re-hash to the recorded value, because that is
    # exactly what evidence_retrieved does before accepting an assertion.
    stored = json.loads((runner.run.root / record.responsePath).read_text(encoding="utf-8"))
    assert response_hash(stored) == record.responseHash
    assert response_hash(response) == record.responseHash


def test_call_ids_are_sequential_and_carry_their_step(runner: ToolRunner):
    runner.call("find_text", {"query": "Order confirmed"}, step_id="step_001")
    runner.call("get_diff", {"eventId": "evt_002"}, step_id="step_001")
    assert [c.id for c in runner.calls] == ["tc_0001", "tc_0002"]
    assert all(c.stepId == "step_001" for c in runner.calls)


def test_a_failing_tool_is_still_logged(runner: ToolRunner):
    # A failed retrieval is evidence too. Logging only what worked would make
    # the trace a record of successes rather than a record of what happened.
    call_id, response = runner.call("get_diff", {"eventId": "evt_999"})
    assert "error" in response
    record = runner.calls[0]
    assert record.id == call_id
    assert record.error and "evt_999" in record.error
    assert (runner.run.root / record.responsePath).exists()


def test_an_unknown_tool_is_logged_and_lists_what_exists(runner: ToolRunner):
    _, response = runner.call("get_everything")
    assert "get_snapshot" in response["available"]
    assert runner.calls[0].error


def test_the_registry_is_the_six_tools_some_stage_actually_offers():
    """Every registered tool must be reachable, or it is a worse tool list.

    SS8.1 listed twelve. Six were offered to NO stage -- reachable only through
    `coverage.py`, the one `investigate()` caller that passed no `tool_names`
    and so received the whole registry by accident -- and one of those six,
    `search_step_library`, had already had its module deleted underneath it and
    degraded to "no library configured" for anything that called it.

    The rule they broke is measured, not aesthetic: more tools means worse tool
    choice, which is the entire reason `tool_names` exists. Making one tool feel
    obligatory lifted calls-per-step from 1.56 to 2.17 and collapsed the effort
    spread from 1.08 to 0.16.

    `get_full_snapshot` went earlier and for its own reason: it existed to be
    the escape hatch that justified scoped capture, and `get_snapshot` returns
    the whole page now.
    """
    assert sorted(TOOLS) == sorted(
        [
            "find_text",
            "get_diff",
            "get_narration",
            "get_network",
            "get_snapshot",
            "see",
        ]
    )


def test_every_tool_is_offered_to_at_least_one_stage():
    """The check that would have caught the six, and catches the next one."""
    from server.pipeline.author import AUTHOR_TOOLS
    from server.pipeline.coverage import COVERAGE_TOOLS
    from server.pipeline.expectations import EXPECTATION_TOOLS
    from server.pipeline.judge import JUDGE_TOOLS

    offered = set(AUTHOR_TOOLS) | set(JUDGE_TOOLS) | set(COVERAGE_TOOLS) | set(EXPECTATION_TOOLS)
    orphans = set(TOOLS) - offered
    assert not orphans, (
        f"{sorted(orphans)} are registered and no stage may call them. Either give "
        f"a stage the tool or delete it -- an unreachable tool is dead weight in "
        f"the one list where length costs accuracy."
    )
    unknown = offered - set(TOOLS)
    assert not unknown, f"{sorted(unknown)} are offered to a stage and do not exist"


def test_every_tool_is_callable_and_serialisable(runner: ToolRunner):
    """Whatever a tool returns has to survive canonical serialization, or the
    hash it is stored under cannot be recomputed."""
    args: dict[str, dict] = {
        "get_snapshot": {"eventId": "evt_002"},
        "get_diff": {"eventId": "evt_002"},
        "get_network": {"eventId": "evt_002"},
        "get_narration": {"fromMs": 0, "toMs": 1000},
        "find_text": {"query": "Order confirmed"},
        "see": {"eventId": "evt_002"},
    }
    assert set(args) == set(TOOLS), "a new tool needs a row here, or it is never called"
    for tool in TOOLS:
        call_id, _ = runner.call(tool, args[tool])
        record = next(c for c in runner.calls if c.id == call_id)
        assert record.error is None, f"{tool} failed: {record.error}"
        stored = json.loads((runner.run.root / record.responsePath).read_text(encoding="utf-8"))
        assert response_hash(stored) == record.responseHash


def test_get_diff_counts_exactly_and_shows_the_readable_half(runner: ToolRunner):
    """A page-wide diff arrives with a tail, and the counts must not depend on it.

    Capturing the whole document is what makes an expected result possible at
    all, and it is also what makes a grid re-render report forty wrapper nodes
    beside the four product names that matter. So the rows are ranked and cut,
    and the counts above them are always the true ones -- "how much changed" and
    "what changed" are different questions, and an agent reading a truncated
    list as a total would conclude the page barely moved.
    """
    from server.evidence.tools import MAX_DIFF_ROWS

    named = [f.diff_node(f"0.{i}", "text", f"Product {i}") for i in range(10)]
    nameless = [f.diff_node(f"1.{i}", "group", "") for i in range(MAX_DIFF_ROWS + 20)]
    store = runner.store
    store.event("evt_003").diff = f.SnapshotDiff(
        added=nameless + named, removed=[], changed=[]
    )

    _, response = runner.call("get_diff", {"eventId": "evt_003"})

    assert response["summary"]["added"] == len(named) + len(nameless)
    assert len(response["added"]) == MAX_DIFF_ROWS
    # Every named node survives the cut, and they come first.
    shown = [n["name"] for n in response["added"]]
    assert shown[:10] == [f"Product {i}" for i in range(10)]
    assert "full=true" in response["note"]


def test_get_diff_full_holds_nothing_back(runner: ToolRunner):
    store = runner.store
    store.event("evt_003").diff = f.SnapshotDiff(
        added=[f.diff_node(f"1.{i}", "group", "") for i in range(60)], removed=[], changed=[]
    )

    _, response = runner.call("get_diff", {"eventId": "evt_003", "full": True})

    assert len(response["added"]) == 60
    assert "note" not in response


def test_find_text_tells_the_agent_when_a_claim_cannot_be_grounded(runner: ToolRunner):
    _, response = runner.call("find_text", {"query": "Payment declined"})
    assert response["count"] == 0
    assert "cannot be grounded" in response["note"]


# --------------------------------------------------------------------------
# against a real recording
# --------------------------------------------------------------------------


def test_queries_a_real_recorded_session(tmp_path: Path):
    path = FIXTURES / "checkout.recording.json"
    if not path.exists():
        pytest.skip("run `pnpm e2e` to regenerate the recorded fixtures")

    recording = Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))
    store = EvidenceStore(recording=recording)
    store.attach_segments(segment_recording(recording, run_id="run_real"))

    # The confirmation the test case is about really is retrievable.
    matches = store.find_text("Order confirmed")
    assert matches, "the confirmation must be findable, or no assertion can cite it"

    # And the mutation that produced it.
    orders = store.find_text("/api/orders")
    assert any(m["kind"] == "network" and m.get("status") == 201 for m in orders)

    # The redacted password must not be retrievable as a literal.
    assert store.find_text("hunter2") == []
