"""Reading back the `.feature` the author wrote.

The root cause the 2026-08-29 change addresses is that no model in this pipeline
had ever seen a feature file: the author emitted JSON, a script composed the
body, and the artifact the tool is judged by was an assembled array. These tests
are about the join between the file and its annotations, and about the fallback
that stops a format slip from costing a run.
"""

from __future__ import annotations

import json

import pytest

from server.config import ProjectConfig
from server.config.project import STYLES
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.pipeline.author import DEFAULT_STYLE, _parse, worked_example
from server.pipeline.featurefile import FeatureParseError, parse_feature
from server.storage.paths import Storage
from tests import factories as f

FEATURE = """\
@checkout
Feature: Order approval

  Orders over a threshold need a manager.

  Scenario: A large order is held
    Given the tester signs in
    When the tester places an order for EUR615
    Then the order is held for approval

  Scenario Outline: Sorting reorders the list
    When the tester sorts by <order>
    Then the first product is <first>

    Examples:
      | order      | first               |
      | price desc | The Autumnal Hamper |
      | price asc  | Marmalade           |
"""


# --------------------------------------------------------------------------
# the parser
# --------------------------------------------------------------------------


def test_the_parser_reads_scenarios_in_the_order_they_were_written():
    parsed = parse_feature(FEATURE)

    assert parsed.name == "Order approval"
    assert parsed.tags == ["checkout"]
    assert parsed.description == "Orders over a threshold need a manager."
    assert [s.name for s in parsed.scenarios] == [
        "A large order is held",
        "Sorting reorders the list",
    ]
    # `lines` is what the annotations are joined against, so document order
    # across the WHOLE file is the contract, not order within a scenario.
    assert [line.text for line in parsed.lines] == [
        "the tester signs in",
        "the tester places an order for EUR615",
        "the order is held for approval",
        "the tester sorts by <order>",
        "the first product is <first>",
    ]


def test_an_examples_table_is_read_as_test_design():
    outline = parse_feature(FEATURE).scenarios[1]

    assert outline.examples is not None
    assert outline.examples.columns == ["order", "first"]
    assert outline.examples.rows[0] == ["price desc", "The Autumnal Hamper"]


def test_a_one_row_table_is_not_a_table():
    # One row is a scenario with extra ceremony, and rendering it as an outline
    # makes a single case look like a designed set.
    text = FEATURE.replace("      | price asc  | Marmalade           |\n", "")
    assert parse_feature(text).scenarios[1].examples is None


def test_a_body_that_forgot_its_feature_line_is_still_read():
    # A model that returns only the scenarios has made a formatting slip, not a
    # mistake about the test. The name is replaced by the author's own `title`.
    text = "  Scenario: A large order is held\n    When the tester orders\n"
    assert [s.name for s in parse_feature(text).scenarios] == ["A large order is held"]


def test_a_background_the_author_wrote_opens_the_first_scenario():
    # `Background` belongs to the renderer, which lifts shared setup out of the
    # SECOND test case's preconditions. Two sources for one thing is how they
    # drift; refusing the run over it would be worse than folding it in.
    text = """\
Feature: X

  Background:
    Given the tester signs in

  Scenario: One
    When the tester orders

  Scenario: Two
    When the tester pays
"""
    parsed = parse_feature(text)
    assert [line.text for line in parsed.scenarios[0].lines] == [
        "the tester signs in",
        "the tester orders",
    ]
    assert [line.text for line in parsed.scenarios[1].lines] == ["the tester pays"]


@pytest.mark.parametrize(
    "text",
    ["", "   ", "this is not gherkin at all, it is a paragraph about a shop"],
)
def test_text_that_is_not_a_feature_raises_rather_than_guessing(text):
    with pytest.raises(FeatureParseError):
        parse_feature(text)


# --------------------------------------------------------------------------
# the join, and the fallback
# --------------------------------------------------------------------------


@pytest.fixture
def bits(tmp_path):
    recording = f.recording(
        events=[
            f.event("evt_001", 0, at=0.0),
            f.event("evt_002", 1, at=1000.0),
        ]
    )
    store = EvidenceStore(recording=recording)
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    runner = ToolRunner(store=store, storage=storage, run=storage.run(recording.id, "run_test"))
    return store, runner


def answer(**over) -> dict:
    base = {
        "feature": (
            "Feature: Order checkout\n"
            "\n"
            "  Scenario: A valid order is confirmed\n"
            "    Given the tester fills in the order\n"
            "    When the tester places it\n"
        ),
        "title": "Order checkout",
        "annotations": [
            {"kind": "step", "id": "step_001", "role": "setup", "events": ["evt_001"]},
            {"kind": "step", "id": "step_002", "role": "test_step", "events": ["evt_002"]},
        ],
    }
    base.update(over)
    return base


def parse(payload, bits, tool_call_ids=None):
    store, runner = bits
    ids = tool_call_ids if tool_call_ids is not None else [c.id for c in runner.calls]
    return _parse(payload, store, runner, ids, ProjectConfig(), None)


def test_the_prose_in_the_file_is_the_prose_that_ships(bits):
    document = parse(answer(), bits)

    assert document.degraded == ""
    assert [s.text for s in document.steps] == [
        "the tester fills in the order",
        "the tester places it",
    ]
    # Not put through `with_subject`. The author wrote a line of a feature file
    # and a reader sees exactly that line; rewriting the subject afterwards is
    # the assembly this change removes.
    assert document.scenarios[0].name == "A valid order is confirmed"


def test_a_verdict_line_attaches_to_the_step_above_it(bits):
    payload = answer(
        feature=(
            "Feature: Order checkout\n"
            "\n"
            "  Scenario: A valid order is confirmed\n"
            "    Given the tester fills in the order\n"
            "    When the tester places it\n"
            "    Then the confirmation appears\n"
        ),
        annotations=[
            {"kind": "step", "id": "step_001", "role": "setup", "events": ["evt_001"]},
            {"kind": "step", "id": "step_002", "role": "test_step", "events": ["evt_002"]},
            {
                "kind": "verdict",
                "evidence": {"eventId": "evt_002", "literal": "nothing retrieved this"},
            },
        ],
    )
    document = parse(payload, bits)

    # Three lines, two steps: a verdict is not a step, and the step count is
    # what `event_coverage` and the review UI both count.
    assert len(document.steps) == 2
    # Nothing was retrieved in this run, so the claim is refused out loud rather
    # than attached -- the one rule the architecture exists to enforce, reached
    # through the file exactly as it was through the old `expected` field.
    assert document.refused and "nothing this run retrieved" in document.refused[0]["reason"]
    assert document.steps[1].why_not


def test_a_scenario_that_opens_with_a_verdict_falls_back(bits):
    # `Then` with no `When` is not a document. Falling back is right: the author
    # has produced something structurally wrong, and spending the single
    # revision round on a FORMAT error is what sank prose-first emission before.
    payload = answer(
        feature=("Feature: X\n\n  Scenario: One\n    Then something happened\n"),
        annotations=[{"kind": "verdict", "evidence": {"eventId": "evt_001", "literal": "x"}}],
        steps=[],
    )
    document = parse(payload, bits)
    assert document.degraded


def test_annotations_that_do_not_line_up_fall_back_rather_than_guessing(bits):
    # Ordinal is the join. A length mismatch means the author lost track of its
    # own file, and inventing a pairing would attach the wrong events to the
    # wrong sentence -- which is worse than a degraded run, because it is wrong
    # and silent.
    payload = answer(annotations=[{"kind": "step", "id": "step_001", "events": ["evt_001"]}])
    document = parse(payload, bits)
    assert document.degraded


def test_an_unparseable_feature_falls_back_to_the_old_shape(bits):
    """A format slip must never cost the run, and never a revision round."""
    payload = {
        "feature": "I could not think of a feature file\nso here is a paragraph instead.\n",
        "annotations": [],
        # The old contract, which the fallback still reads.
        "steps": [
            {
                "id": "step_001",
                "keyword": "When",
                "role": "test_step",
                "text": "the tester places the order",
                "events": ["evt_001", "evt_002"],
            }
        ],
    }
    document = parse(payload, bits)

    assert document.degraded == "", "the JSON path is a complete answer, not a degradation"
    assert [s.text for s in document.steps] == ["the tester places the order"]


def test_a_one_line_feature_is_the_old_contracts_feature_NAME(bits):
    # Both shapes have to survive one parser while the prompt changes, and the
    # old one put the feature's NAME in `feature`. Trying to parse a name as a
    # document would degrade every run made against the previous prompt.
    payload = {
        "feature": "Order checkout",
        "steps": [
            {
                "id": "step_001",
                "keyword": "When",
                "role": "test_step",
                "text": "the tester places the order",
                "events": ["evt_001", "evt_002"],
            }
        ],
    }
    document = parse(payload, bits)
    assert document.title == "Order checkout"
    assert document.degraded == ""


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------


@pytest.mark.parametrize("style", STYLES)
def test_every_style_shows_the_author_an_actual_feature_file(style):
    """The whole point. A style is a worked example, not a rule.

    Every content rule ever added to a drafting prompt here measured at or near
    zero uptake, and the capabilities that never fired -- `see`, `Examples` --
    were each named once in the rules and zero times in the example. So each
    style file has to CONTAIN the things it wants used.

    Parametrised over `STYLES` rather than a list written out here: a style is
    the one thing in this project you add by writing a file, so the check that
    it is a GOOD file has to find the next one without being told.
    """
    example = worked_example(style)

    assert example, f"{style} is offered in project.yaml and has no file behind it"
    assert "```gherkin" in example, "the author must be shown Gherkin, not told about it"
    assert "Scenario:" in example
    assert "Scenario Outline:" in example and "Examples:" in example
    assert "see(" in example, "a capability absent from the example is never used"
    assert "get_network(" in example
    assert '"predicate"' in example, "the predicate has to appear where it is warranted"
    # And the annotations in it must be the shape the parser reads.
    assert '"kind": "verdict"' in example and '"kind": "step"' in example


def test_every_style_is_a_file_and_not_a_fallback():
    """`worked_example` falls back to the default for an unknown name, which is
    right for a typo in `project.yaml` and would silently hide a style listed in
    `STYLES` with no file beside it -- every run in that style would quietly get
    the automation example instead."""
    for style in STYLES:
        if style == DEFAULT_STYLE:
            continue
        assert worked_example(style) != worked_example(DEFAULT_STYLE), (
            f"{style} is in STYLES and falls back to {DEFAULT_STYLE}: the file "
            f"server/pipeline/styles/{style}.md is missing"
        )


def test_the_example_in_every_style_is_one_the_parser_can_read():
    """A worked example the pipeline itself would reject teaches a broken shape."""
    for style in STYLES:
        example = worked_example(style)
        body = example.split("```gherkin", 1)[1].split("```", 1)[0]
        parsed = parse_feature(body)

        payload = json.loads(example.split("```json", 1)[1].split("```", 1)[0])
        assert len(payload["annotations"]) == len(parsed.lines), (
            f"the {style} example's annotations do not line up with its own feature "
            f"file, so the shape it teaches would fall back"
        )

        # And the join is by the line, not by ordinal -- an example whose
        # annotations do not echo its own prose teaches the one shape the
        # author cannot get away with.
        lines = [line.text for line in parsed.lines]
        for annotation in payload["annotations"]:
            assert annotation["line"] in lines, (
                f"the {style} example annotates {annotation['line']!r}, which is "
                f"not a line in its own feature file"
            )


def test_an_unknown_style_falls_back_rather_than_losing_the_run():
    # A typo in project.yaml costs the wrong house style, which is visible and
    # fixable by whoever made the typo. It must not cost a recording.
    assert worked_example("nonesuch") == worked_example(DEFAULT_STYLE)


# --------------------------------------------------------------------------
# the join is self-verifying, because ordinal alone was not
# --------------------------------------------------------------------------


def echoing(*, drop: int | None = None) -> dict:
    """A three-line scenario whose annotations echo their lines."""
    payload = {
        "feature": (
            "Feature: Order checkout\n"
            "\n"
            "  Scenario: A valid order is confirmed\n"
            "    Given the tester fills in the order\n"
            "    When the tester places it\n"
            "    Then the confirmation appears\n"
        ),
        "title": "Order checkout",
        "annotations": [
            {
                "kind": "step",
                "line": "the tester fills in the order",
                "id": "step_001",
                "role": "setup",
                "events": ["evt_001"],
            },
            {
                "kind": "step",
                "line": "the tester places it",
                "id": "step_002",
                "role": "test_step",
                "events": ["evt_002"],
            },
            {
                "kind": "verdict",
                "line": "the confirmation appears",
                "evidence": {"eventId": "evt_002", "literal": "nothing retrieved this"},
            },
        ],
    }
    if drop is not None:
        del payload["annotations"][drop]
    return payload


def test_a_forgotten_annotation_costs_its_own_line_and_nothing_else(bits):
    """The failure that killed the ordinal join, on its first real run.

    A model wrote a six-line document and returned five annotations, having
    forgotten the `Given` that opened its second scenario. Under a positional
    join that is not "one line loses its events" -- every line after it is
    silently attributed to its neighbour, which is worse than a degraded run
    because it is wrong and quiet. The whole document was thrown away instead.

    Echoing the line makes the join self-verifying: the forgotten line gets no
    events, `event_coverage` reports the unaccounted event, and every other line
    keeps exactly what it was given.
    """
    document = parse(echoing(drop=0), bits)

    assert document.degraded == ""
    steps = document.steps
    assert [s.text for s in steps] == ["the tester fills in the order", "the tester places it"]
    # The forgotten line lost its own events and stole nobody else's.
    assert steps[0].event_ids == []
    assert steps[1].event_ids == ["evt_002"]


def test_an_annotation_for_a_line_that_is_not_in_the_file_is_dropped(bits):
    payload = echoing()
    payload["annotations"].insert(
        1, {"kind": "step", "line": "a sentence nobody wrote", "events": ["evt_001"]}
    )
    document = parse(payload, bits)

    assert [s.text for s in document.steps] == [
        "the tester fills in the order",
        "the tester places it",
    ]
    assert document.steps[1].event_ids == ["evt_002"]


def test_an_echo_that_differs_only_in_spacing_still_matches(bits):
    payload = echoing()
    payload["annotations"][1]["line"] = "  the tester   places it.  "
    assert parse(payload, bits).steps[1].event_ids == ["evt_002"]


def test_a_positional_claim_binds_to_its_own_events_retrieval(bits):
    """A page is identified by its event, not by a string that appears on several.

    Observed on a live run: the author claimed the list held 9 items at evt_001,
    had retrieved both events' snapshots, and the literal-driven search handed
    back evt_002's -- because "Showing 9 of 24 products" is the text of the
    CHANGE and appears in both. Counting evt_002's list then said 3, and a true
    claim was refused for a reason that was about the wrong page.

    Nothing is loosened: the retrieval must still be one this run made, and the
    predicate must still hold against it.
    """
    store, runner = bits
    first, _ = runner.call("get_snapshot", {"eventId": "evt_001"})
    second, _ = runner.call("get_snapshot", {"eventId": "evt_002"})

    document = parse(
        {
            "feature": (
                "Feature: Filtering\n"
                "\n"
                "  Scenario: The list narrows\n"
                "    When the tester filters the list\n"
                "    Then the list holds one product\n"
            ),
            "title": "Filtering",
            "annotations": [
                {
                    "kind": "step",
                    "line": "the tester filters the list",
                    "id": "step_001",
                    "role": "test_step",
                    "events": ["evt_001", "evt_002"],
                },
                {
                    "kind": "verdict",
                    "line": "the list holds one product",
                    "evidence": {
                        "eventId": "evt_001",
                        "literal": "Checkout",
                        "predicate": {
                            "form": "count",
                            "container": {"role": "main"},
                            "n": 0,
                        },
                    },
                },
            ],
        },
        bits,
    )

    claims = [a for s in document.steps for a in s.assertions]
    assert claims, f"the claim was refused: {document.refused}"
    # evt_001's retrieval, not the most recent one that happened to contain the
    # literal -- which here is evt_002's, made afterwards.
    assert claims[0].evidence.toolCallId == first
    assert claims[0].evidence.toolCallId != second


# --------------------------------------------------------------------------
# the shape a model actually returns
# --------------------------------------------------------------------------


def test_the_feature_is_read_from_its_own_fenced_block(bits):
    """The contract is two fenced blocks, because that is what the example shows.

    It was "JSON and nothing else, with a `feature` key". The example put the
    Gherkin in a ```gherkin fence and the annotations in a ```json fence beside
    it -- and on the checkout recording a real model reproduced the JSON block
    faithfully, including its lack of a `feature` key, and dropped the Gherkin
    entirely. A complete, correct set of annotations with nothing to attach them
    to, falling all the way through to the deterministic fallback and shipping
    "the tester interacts with Password".

    **The example outweighs the rules**, which is this project's most-repeated
    law, so the rule changed to match the example rather than the other way
    round.
    """
    from server.llm.gemini import parse_json_answer

    raw = (
        "```gherkin\n"
        "Feature: Order checkout\n"
        "\n"
        "  Scenario: A valid order is confirmed\n"
        "    Given the tester fills in the order\n"
        "    When the tester places it\n"
        "```\n"
        "\n"
        "```json\n"
        '{"title": "Order checkout", "annotations": ['
        '{"kind": "step", "line": "the tester fills in the order",'
        ' "id": "step_001", "role": "setup", "events": ["evt_001"]},'
        '{"kind": "step", "line": "the tester places it",'
        ' "id": "step_002", "role": "test_step", "events": ["evt_002"]}]}\n'
        "```\n"
    )

    store, runner = bits
    document = _parse(
        parse_json_answer(raw), store, runner, [], ProjectConfig(), None, answer_text=raw
    )

    assert document.degraded == "", "the two-block answer fell through to the fallback"
    assert [s.text for s in document.steps] == [
        "the tester fills in the order",
        "the tester places it",
    ]
    assert document.steps[0].event_ids == ["evt_001"]


def test_the_json_block_is_found_even_when_it_is_not_the_first_fence():
    # `parse_json_answer` took the FIRST fence, which is now the Gherkin one.
    # The balanced-object fallback would have rescued it here by luck, and only
    # while no `{` appears in the feature body before the JSON.
    from server.llm.gemini import parse_json_answer

    raw = '```gherkin\nFeature: X {not json}\n```\n\n```json\n{"title": "X"}\n```\n'
    assert parse_json_answer(raw) == {"title": "X"}
