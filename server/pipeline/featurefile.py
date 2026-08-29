"""Read a `.feature` the author wrote, so the author can write one.

## Why this exists

No model in this pipeline had ever seen a `.feature` file. The author emitted
JSON, `narrative.py` composed the body and `gherkin.py` wrote the file, so the
one artifact the tool is judged by was assembled by a script from parts none of
which were Gherkin. The output read like an assembled array because it *was*
one, and two of four shipped features carried the tell:

    When the order is not processed                     <- a state written as an
                                                           action, and no verdict
    And the receipt displays the total amount charged   <- an assertion as a step
    Then the receipt displays the total amount charged   <- the same verdict twice

It also broke this project's own most-repeated law in the most literal way
available: **a worked example outweighs its rules, and what is absent from the
example does not happen.** The author's worked example taught a model to write
Gherkin without ever showing it any Gherkin.

So the author now writes the file, and this module reads it back.

## What is joined to what, and why by ORDINAL

The author returns two things: the Gherkin body, and one annotation per step
line **in document order**. The prose lives in the file and nowhere else -- a
step's text and a verdict's text are the line, not a duplicate field -- and the
annotation carries only what prose cannot: which events a line accounts for,
which literal proves it, why there is no verdict.

The join is positional, and the alternatives are worse. Line numbers ask a model
to count lines in a string it has just generated. Repeating the text as a key
duplicates the prose, which reintroduces exactly the drift this change removes,
and breaks outright on two steps that legitimately read the same. Ordinal is the
one key a model can produce reliably, and a length mismatch is detectable --
which matters more than being clever, because a detected mismatch falls back.

## The fallback is the safety property

A whole-document rewrite that fails to parse must not cost the run its single
revision round -- that objection is on the record as the reason prose-first
emission was rejected once already. So a body that does not parse, or whose
annotations do not line up, is not an error: `author._parse` falls back to the
JSON path it has always had and marks the document `degraded`. The author is
never punished for a format slip, and a malformed feature cannot reach disk.

## What this does NOT own

`Background` is still the renderer's. A recording that yields two test cases
lifts the first case's setup into the second's preconditions
(`run._build_case`), and a Background the author wrote by hand would be a second
source of truth for the same thing. The prompt asks for scenarios only; a
`Background` written anyway is folded in as leading setup steps of the first
scenario rather than refused, because losing a run to a formatting preference is
the worse failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server.models import ScenarioExamples

#: Every keyword a step line can open with. `But` is included and `Step.keyword`
#: now carries it: the author's parser accepted `but` for a long time while the
#: schema's enum did not, so a document written with one was a validation error
#: waiting for the first model that used it.
KEYWORDS = ("Given", "When", "Then", "And", "But")


class FeatureParseError(ValueError):
    """The author's text is not a feature file. Never fatal -- see the fallback."""


@dataclass
class ParsedLine:
    """One step line: its keyword and its prose, with the keyword stripped."""

    keyword: str
    text: str
    #: True for a line the parser called an Outcome and the author annotated as
    #: a verdict. Decided by the annotation, not by the keyword -- `Then` is a
    #: hint about narrative position and `And` says nothing at all.
    line_no: int = 0


@dataclass
class ParsedScenario:
    name: str
    tags: list[str] = field(default_factory=list)
    lines: list[ParsedLine] = field(default_factory=list)
    examples: ScenarioExamples | None = None


@dataclass
class ParsedFeature:
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    scenarios: list[ParsedScenario] = field(default_factory=list)

    @property
    def lines(self) -> list[ParsedLine]:
        """Every step line in the whole document, in the order it was written.

        This is what the annotations are joined against, so it has to walk the
        scenarios in exactly the order they appear in the text.
        """
        return [line for scenario in self.scenarios for line in scenario.lines]


def parse_feature(text: str) -> ParsedFeature:
    """Read a feature body with Cucumber's own parser.

    Not a regex, and not for pedantry: "valid Gherkin" means whatever that
    parser accepts, and the same parser is what `gherkin_parses` will run over
    the rendered output. Reading and checking with one implementation means the
    author cannot write something that reads here and fails the gate.
    """
    if not isinstance(text, str) or not text.strip():
        raise FeatureParseError("the author returned no feature text")

    try:
        from gherkin.parser import Parser
    except ImportError as exc:  # pragma: no cover - declared in pyproject
        raise FeatureParseError("gherkin-official is not installed") from exc

    try:
        document = Parser().parse(_ensure_feature_header(text))
    except Exception as exc:  # noqa: BLE001 - the parser raises its own types
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise FeatureParseError(first) from exc

    feature = document.get("feature")
    if not isinstance(feature, dict):
        raise FeatureParseError("no Feature: block")

    out = ParsedFeature(
        name=str(feature.get("name") or "").strip(),
        description=_dedent(str(feature.get("description") or "")),
        tags=[str(t.get("name", "")).lstrip("@") for t in feature.get("tags") or []],
    )

    # A `Background` the author wrote anyway. Its steps open the first scenario
    # rather than becoming a block of their own; see the module docstring.
    background: list[ParsedLine] = []
    for child in feature.get("children") or []:
        if isinstance(child, dict) and isinstance(child.get("background"), dict):
            background = _lines(child["background"])

    for child in feature.get("children") or []:
        if not isinstance(child, dict) or not isinstance(child.get("scenario"), dict):
            continue
        raw = child["scenario"]
        scenario = ParsedScenario(
            name=str(raw.get("name") or "").strip(),
            tags=[str(t.get("name", "")).lstrip("@") for t in raw.get("tags") or []],
            lines=_lines(raw),
            examples=_examples(raw),
        )
        if background and not out.scenarios:
            scenario.lines = background + scenario.lines
        out.scenarios.append(scenario)

    if not out.scenarios:
        raise FeatureParseError("the feature has no scenarios")
    if not out.lines:
        raise FeatureParseError("the feature has no steps")
    return out


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def _ensure_feature_header(text: str) -> str:
    """Accept a body that forgot its `Feature:` line.

    The author is asked for a whole file and mostly writes one, but a model that
    returns only the scenarios has made a formatting slip rather than a mistake
    about the test, and losing the document over it would be the format-error
    failure this design set out to avoid. The name is replaced downstream by the
    author's own `feature` field in any case.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("@"):
            continue
        if stripped.startswith("Feature:"):
            return text
        break
    return "Feature: Generated\n\n" + text


def _lines(block: dict) -> list[ParsedLine]:
    out: list[ParsedLine] = []
    for step in block.get("steps") or []:
        if not isinstance(step, dict):
            continue
        keyword = str(step.get("keyword") or "").strip()
        text = str(step.get("text") or "").strip()
        if not text:
            continue
        out.append(
            ParsedLine(
                keyword=keyword if keyword in KEYWORDS else "When",
                text=text,
                line_no=int((step.get("location") or {}).get("line") or 0),
            )
        )
    return out


def _examples(scenario: dict) -> ScenarioExamples | None:
    """The author's own `Examples` table, when it wrote one.

    A judgement about test design -- one flow exercised with several sets of
    values -- and distinct from `parameters: outline`, which lifts redaction
    placeholders and is a rendering setting. Two rows minimum: one row is not a
    table, it is a scenario with extra ceremony.
    """
    for block in scenario.get("examples") or []:
        if not isinstance(block, dict):
            continue
        header = block.get("tableHeader")
        body = block.get("tableBody") or []
        if not isinstance(header, dict) or len(body) < 2:
            continue
        columns = [str(c.get("value") or "") for c in header.get("cells") or []]
        rows = [
            [str(c.get("value") or "") for c in (row.get("cells") or [])]
            for row in body
            if isinstance(row, dict)
        ]
        rows = [r for r in rows if len(r) == len(columns)]
        if columns and len(rows) >= 2:
            return ScenarioExamples(columns=columns, rows=rows)
    return None


def _dedent(text: str) -> str:
    """The description block, with the parser's indentation taken back off."""
    lines = [line.strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line).strip()


__all__ = [
    "KEYWORDS",
    "FeatureParseError",
    "ParsedFeature",
    "ParsedLine",
    "ParsedScenario",
    "parse_feature",
]
