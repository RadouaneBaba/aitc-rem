"""Per-project output settings.

The pipeline decides what is *true*; this file decides how it *reads*. Those are
different jobs, and conflating them is why generated test suites feel like
somebody else's output rather than the team's own.

Ten QA teams write the same login ten ways -- "the tester signs in", "I sign
in", "the user authenticates" -- and none of them is wrong. SS12 solves the
expensive half of that with a step library; this solves the cheap half by
letting a team state its house style once, in a file a QA lead can edit without
reading any Python.

Everything here has a default that produces good output, so a project with no
`config/project.yaml` at all still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from server.storage.paths import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "config" / "project.yaml"
ORIGINS_PATH = REPO_ROOT / "config" / "allowed_origins.yaml"

#: How a step refers to the person executing it. Anything is allowed -- these
#: are the ones worth listing in the file as examples.
KNOWN_VOICES = ("the tester", "the user", "I", "the admin")

TRACE_MODES = ("sidecar", "none")
PARAMETER_MODES = ("inline", "outline")
QASE_STEP_MODES = ("classic", "gherkin")

#: What to do when a recording touches an origin that is not on the allowlist
#: (SS7.3). The allowlist exists because FREE-TIER prompts are training-eligible
#: and human-reviewable -- it is a property of the tier, not of the provider. On
#: a paid endpoint with a no-training term the whole question is moot, which is
#: why this is a setting a project states once rather than a flag on every run.
ORIGIN_POLICIES = ("allowlist", "warn", "off")


@dataclass(frozen=True)
class ProjectConfig:
    """House style for the rendered artifacts."""

    #: Subject of every step sentence. "I" switches the naming stage to first
    #: person, which is the classic Cucumber register.
    voice: str = "the tester"

    #: Applied to every test case on top of whatever composition proposes.
    tags: tuple[str, ...] = ()

    #: `sidecar` writes `<case>.trace.md` next to the feature file and keeps the
    #: feature body free of traceability comments. `none` writes neither -- the
    #: evidence still lives in `ir.json` and `trace.json`, which is what the
    #: validators read; this only governs what a human is handed.
    trace: str = "sidecar"

    #: `inline` quotes captured values and redaction placeholders directly in
    #: step text and emits a plain `Scenario`. `outline` lifts the placeholders
    #: into a `Scenario Outline` with an `Examples` table.
    #:
    #: inline is the default because a manual tester executes the test top to
    #: bottom, and a single-row Examples table makes them look in two places for
    #: one value. Outline earns its keep when a project genuinely runs several
    #: data rows.
    parameters: str = "inline"

    #: Filename stem for the rendered feature, formatted with `caseId`, `title`
    #: and `recordingId`.
    feature_name: str = "{caseId}"

    #: Written into the feature header so a reader can find the evidence. Off
    #: for teams who want the file to look hand-written.
    header: bool = True

    #: Extra formats to emit alongside the feature file (SS11). Gherkin and its
    #: sidecar are always written -- the validators read them.
    exports: tuple[str, ...] = ()

    #: SS11.3 -- a plain issue works for every Jira there is. The type is
    #: configurable because teams model tests as Test, Task or Story and none
    #: of them is wrong.
    jira_issue_type: str = "Test"
    jira_project_key: str = ""

    #: SS11 -- Qase. `classic` is the action/expected grid the Qase UI shows a
    #: manual tester; `gherkin` sends the scenario as it stands. Classic by
    #: default because the point of an export is to meet a team where they are.
    qase_steps: str = "classic"
    qase_project_code: str = ""
    qase_suite: str = ""

    #: SS11 -- Xray. Its feature-file import takes the `.feature` this project
    #: already produces, so there is no exporter to write; what it needs is the
    #: `@TEST_<KEY>` tag that makes a re-import update an existing Test instead
    #: of creating a second one. Empty means "do not emit it".
    xray_test_key: str = ""

    #: `allowlist` refuses to send when an origin is unknown, `warn` sends and
    #: says so, `off` does not check.
    #:
    #: `warn` is the default because refusing was the wrong shape of gate: the
    #: API path has always reported rather than refused, so the two entry points
    #: disagreed, and a tester who wants to record a real site is not doing
    #: anything wrong -- they need to know what it costs, not to be stopped.
    origin_policy: str = "warn"

    @property
    def first_person(self) -> bool:
        return self.voice.strip().lower() == "i"

    def feature_stem(self, *, case_id: str, title: str, recording_id: str) -> str:
        try:
            stem = self.feature_name.format(caseId=case_id, title=title, recordingId=recording_id)
        except (KeyError, IndexError):
            # A malformed template must not lose someone their output.
            stem = case_id
        return _slug(stem) or case_id


def load_project_config(path: Path | None = None) -> ProjectConfig:
    """Read `config/project.yaml`, falling back to the defaults.

    Unknown keys are ignored rather than fatal: a config file is edited by
    hand, and a typo in an optional setting should not stop a pipeline run that
    would otherwise have produced good output.
    """
    data = _read_yaml(path or DEFAULT_PATH)
    if not isinstance(data, dict):
        return ProjectConfig()

    fields: dict[str, Any] = {}
    if isinstance(data.get("voice"), str) and data["voice"].strip():
        fields["voice"] = data["voice"].strip()
    if isinstance(data.get("tags"), list):
        fields["tags"] = tuple(str(t).strip().lstrip("@") for t in data["tags"] if str(t).strip())
    if data.get("trace") in TRACE_MODES:
        fields["trace"] = data["trace"]
    if data.get("parameters") in PARAMETER_MODES:
        fields["parameters"] = data["parameters"]
    if isinstance(data.get("feature_name"), str) and data["feature_name"].strip():
        fields["feature_name"] = data["feature_name"].strip()
    if isinstance(data.get("header"), bool):
        fields["header"] = data["header"]
    if isinstance(data.get("exports"), list):
        fields["exports"] = tuple(str(e).strip().lower() for e in data["exports"] if str(e).strip())
    if data.get("origin_policy") in ORIGIN_POLICIES:
        fields["origin_policy"] = data["origin_policy"]

    qase = data.get("qase")
    if isinstance(qase, dict):
        if qase.get("steps") in QASE_STEP_MODES:
            fields["qase_steps"] = qase["steps"]
        if isinstance(qase.get("project_code"), str):
            fields["qase_project_code"] = qase["project_code"].strip()
        if isinstance(qase.get("suite"), str):
            fields["qase_suite"] = qase["suite"].strip()

    xray = data.get("xray")
    if isinstance(xray, dict) and isinstance(xray.get("test_key"), str):
        fields["xray_test_key"] = xray["test_key"].strip()

    jira = data.get("jira")
    if isinstance(jira, dict):
        if isinstance(jira.get("issue_type"), str) and jira["issue_type"].strip():
            fields["jira_issue_type"] = jira["issue_type"].strip()
        if isinstance(jira.get("project_key"), str):
            fields["jira_project_key"] = jira["project_key"].strip()

    return ProjectConfig(**fields)


def load_allowed_origins(path: Path | None = None) -> list[str]:
    """The SS7.3 pre-send allowlist.

    Parsed with the YAML library rather than by hand: this gate decides whether
    a real application's snapshots may be sent to a training-eligible endpoint,
    and a list format the parser and the author disagree about is the wrong
    place to save a dependency.
    """
    data = _read_yaml(path or ORIGINS_PATH)
    if isinstance(data, dict):
        data = data.get("allowed") or data.get("origins") or []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None


def _slug(text: str) -> str:
    """Filesystem-safe, but not lowercased.

    A recording id is `rec_MSYWWF2M9EW5`; folding its case makes the filename
    stop matching the id the run directory, the trace and every log line use.
    """
    out: list[str] = []
    for ch in text.strip():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")


__all__ = [
    "KNOWN_VOICES",
    "ProjectConfig",
    "load_allowed_origins",
    "load_project_config",
]
