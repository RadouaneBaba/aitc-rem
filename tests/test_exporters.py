"""Excel and Jira export (SS11.2, SS11.3, milestone 15).

    "One IR, three renderers. No format is second-class, and a fourth output
     means writing a renderer, not touching the pipeline."

The `.feature` file is the proof of the architecture; Excel is what the wedge
population of SS2.2 actually opens on Monday. So these tests are about the
things that would make a tester distrust a generated spreadsheet or issue --
losing a step, hiding a warning, or letting an unverified coverage suggestion
reach somebody as if it were a test step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.config import ProjectConfig
from server.renderers import EXPORTERS, ExcelExporter, JiraExporter, export_all
from server.renderers.gherkin import render_test_case
from server.renderers.jira import build_issue
from tests import factories as f
from tests.test_gherkin import build_case

load_workbook = pytest.importorskip("openpyxl").load_workbook


def document(**kwargs):
    return f.ir_document(test_cases=[build_case(**kwargs)])


def export(exporter, tmp_path: Path, ir=None, config: ProjectConfig | None = None):
    return exporter.export(ir or document(), out_dir=tmp_path, config=config or ProjectConfig())


def sheet_rows(path: Path, name: str | None = None) -> list[tuple]:
    workbook = load_workbook(path)
    sheet = workbook[name] if name else workbook[workbook.sheetnames[0]]
    return list(sheet.iter_rows(values_only=True))


def cells(rows: list[tuple]) -> str:
    return "\n".join(" | ".join(str(c) for c in row if c is not None) for row in rows)


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------


def test_every_step_reaches_the_spreadsheet_in_order(tmp_path: Path):
    result = export(ExcelExporter(), tmp_path)
    rows = sheet_rows(result.files[0])

    numbered = [r for r in rows if isinstance(r[0], int)]
    assert [r[0] for r in numbered] == [1, 2, 3]
    assert [r[1] for r in numbered] == ["Given", "When", "And"]
    assert "signs in" in numbered[0][2]


def test_an_expected_result_sits_beside_the_step_that_produced_it(tmp_path: Path):
    # A tester executing step 3 needs to see what to check without scrolling
    # to find it on a row of its own.
    result = export(ExcelExporter(), tmp_path)
    numbered = [r for r in sheet_rows(result.files[0]) if isinstance(r[0], int)]

    submit = next(r for r in numbered if "submits the order form" in r[2])
    assert submit[3] == "the confirmation banner appears"
    # ...and a step with no outcome does not borrow one.
    assert not next(r for r in numbered if "signs in" in r[2])[3]


def test_the_supporting_sheets_are_always_present(tmp_path: Path):
    # An empty Parameters sheet saying "this test needs none" is information.
    # A missing one is a question.
    result = export(ExcelExporter(), tmp_path)
    names = load_workbook(result.files[0]).sheetnames

    assert {"Preconditions", "Parameters", "Warnings"} <= set(names)


def test_parameters_get_a_column_for_the_tester_to_fill_in(tmp_path: Path):
    ir = document(parameters=[f.parameter("user_email_1", "<<user_email_1>>", "email")])
    result = export(ExcelExporter(), tmp_path, ir)
    text = cells(sheet_rows(result.files[0], "Parameters"))

    assert "<<user_email_1>>" in text
    assert "Your value" in text


def test_a_warning_is_a_sheet_rather_than_a_colour(tmp_path: Path):
    # SS6.8 -- a tool that admits what it does not know stays trusted. A
    # spreadsheet has no styling convention the reader shares.
    ir = document()
    ir.testCases[0].steps[0].confidence = "low"
    ir.testCases[0].steps[1].escalation = "did a file download?"

    result = export(ExcelExporter(), tmp_path, ir)
    text = cells(sheet_rows(result.files[0], "Warnings"))

    assert "low confidence" in text
    assert "unanswered question" in text


def test_a_sheet_name_survives_excels_limits(tmp_path: Path):
    # Excel truncates past 31 characters and rejects []:*?/\ silently, so two
    # long names that collide after truncation would cost one of them its
    # sheet.
    long_name = "Submitting an order that requires manager approval above EUR500"
    ir = f.ir_document(
        test_cases=[
            build_case(ident="tc_a", scenarioName=long_name),
            build_case(ident="tc_b", scenarioName=long_name + " [again]"),
        ]
    )
    result = export(ExcelExporter(), tmp_path, ir)
    names = load_workbook(result.files[0]).sheetnames

    assert len(set(names)) == len(names), names
    assert all(len(n) <= 31 for n in names), names
    assert not any(set("[]:*?/\\") & set(n) for n in names), names


def test_coverage_suggestions_get_their_own_labelled_sheet(tmp_path: Path):
    # SS9.8 -- never rendered as steps. A suggestion that reaches somebody as a
    # test row is the failure this separation exists to prevent.
    ir = document(
        suggestions=[
            f.coverage_suggestion(
                "sug_001", "An invalid-email path is untested.", "validation_path"
            )
        ]
    )
    result = export(ExcelExporter(), tmp_path, ir)
    workbook = load_workbook(result.files[0])

    assert "Coverage (unverified)" in workbook.sheetnames
    assert "invalid-email" not in cells(sheet_rows(result.files[0]))
    assert "invalid-email" in cells(sheet_rows(result.files[0], "Coverage (unverified)"))


def test_a_test_case_that_checks_nothing_says_so(tmp_path: Path):
    ir = document()
    for step in ir.testCases[0].steps:
        step.assertions = []

    result = export(ExcelExporter(), tmp_path, ir)
    assert any("procedure rather than a test" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Jira
# --------------------------------------------------------------------------


def test_the_issue_is_built_but_never_sent(tmp_path: Path):
    # Posting needs a site, a project key and an API token. A run that silently
    # required credentials would be a run most people cannot make.
    result = export(JiraExporter(), tmp_path)

    assert result.files[0].suffix == ".json"
    assert result.payload
    assert any("not sent" in w for w in result.warnings)


def test_the_issue_carries_a_summary_type_and_labels():
    case = build_case(tags=["checkout", "@smoke"])
    issue = build_issue(case, ProjectConfig(tags=("regression",)))

    assert issue["fields"]["summary"] == "Submitting a valid order shows the confirmation"
    assert issue["fields"]["issuetype"] == {"name": "Test"}
    # Jira rejects a label containing a space, and a leading @ is Gherkin's.
    assert issue["fields"]["labels"] == ["checkout", "smoke", "regression"]


def test_the_project_key_is_omitted_rather_than_guessed():
    # An issue posted into the wrong project is worse than one that fails to
    # post, so an unset key is left out for the caller to supply.
    assert "project" not in build_issue(build_case(), ProjectConfig())["fields"]
    assert build_issue(build_case(), ProjectConfig(jira_project_key="QA"))["fields"]["project"] == {
        "key": "QA"
    }


def test_the_steps_become_an_adf_table_with_a_header_row():
    description = build_issue(build_case(), ProjectConfig())["fields"]["description"]
    table = next(c for c in description["content"] if c["type"] == "table")

    assert table["content"][0]["content"][0]["type"] == "tableHeader"
    assert len(table["content"]) == 4, "a header row plus one row per step"


def test_an_expected_result_lands_in_its_own_column():
    description = build_issue(build_case(), ProjectConfig())["fields"]["description"]
    table = next(c for c in description["content"] if c["type"] == "table")
    last = table["content"][-1]["content"][-1]

    assert "confirmation banner appears" in json.dumps(last)


def test_coverage_suggestions_never_enter_the_steps_table():
    case = build_case(
        suggestions=[
            f.coverage_suggestion(
                "sug_001", "An invalid-email path is untested.", "validation_path"
            )
        ]
    )
    description = build_issue(case, ProjectConfig())["fields"]["description"]
    table = next(c for c in description["content"] if c["type"] == "table")

    assert "invalid-email" not in json.dumps(table)
    assert "invalid-email" in json.dumps(description)
    assert "unverified" in json.dumps(description).lower()


def test_the_attachments_name_the_evidence_that_belongs_with_the_issue():
    # SS11.3 -- the .feature file, the evidence and the recording travel with
    # the issue, or a reader has the claims without the provenance.
    issue = build_issue(build_case(), ProjectConfig())
    assert issue["aitcRem"]["attachments"] == [
        "tc_case_001.feature",
        "tc_case_001.trace.md",
        "recording.json",
    ]


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------


def test_a_project_gets_only_the_formats_it_asked_for(tmp_path: Path):
    results = export_all(document(), out_dir=tmp_path, config=ProjectConfig(), names=["xlsx"])

    assert [r.exporter for r in results] == ["xlsx"]
    assert not list(tmp_path.glob("*.jira.json"))


def test_an_unknown_format_is_reported_rather_than_ignored(tmp_path: Path):
    # A typo that silently produces no spreadsheet is worse than an error: the
    # tester finds out when they go looking for the file.
    results = export_all(document(), out_dir=tmp_path, config=ProjectConfig(), names=["xlsx2"])

    assert results[0].files == []
    assert any("no exporter called" in w for w in results[0].warnings)
    assert any("xlsx" in w for w in results[0].warnings), "it should say what is available"


def test_asking_twice_exports_once(tmp_path: Path):
    results = export_all(
        document(), out_dir=tmp_path, config=ProjectConfig(), names=["xlsx", "xlsx"]
    )
    assert len(results) == 1


def test_every_registered_exporter_satisfies_the_interface(tmp_path: Path):
    # SS11's claim that a fourth output is a new file rather than a refactor is
    # only true while they all share one shape.
    for name, exporter in EXPORTERS.items():
        result = exporter().export(document(), out_dir=tmp_path, config=ProjectConfig())
        assert result.exporter == name
        assert result.files, name
        assert all(p.exists() for p in result.files), name


# --------------------------------------------------------------------------
# Qase (SS11)
# --------------------------------------------------------------------------


def test_qase_builds_the_payload_and_does_not_send_it(tmp_path: Path):
    # Same bargain as Jira, for the same reason: a run that silently required an
    # API token would be a run most people cannot make. The warning carries the
    # exact command so nobody has to go and find it.
    from server.renderers.qase import QaseExporter

    result = QaseExporter().export(f.ir_document(), out_dir=tmp_path, config=ProjectConfig())
    assert result.files and result.files[0].suffix == ".json"
    assert any("curl -X POST" in w for w in result.warnings)
    assert any("not sent" in w for w in result.warnings)


def test_qase_sends_one_request_for_the_whole_run(tmp_path: Path):
    # Qase takes an array. N separate calls would be N chances to half-import a
    # suite and leave somebody reconciling it by hand.
    from server.renderers.qase import QaseExporter

    ir = f.ir_document(test_cases=[f.test_case("tc_1"), f.test_case("tc_2")])
    result = QaseExporter().export(ir, out_dir=tmp_path, config=ProjectConfig())
    assert len(result.files) == 1
    assert len(result.payload["cases"]) == 2


def test_an_expected_result_lands_on_the_row_that_produced_it(tmp_path: Path):
    # The classic grid is what a manual tester reads in the Qase UI, and it is
    # built from the same narrative as the feature file, so the two cannot
    # drift. An expected result is not an action and does not get its own row.
    from server.renderers.qase import build_case

    case = f.test_case(
        steps=[
            f.step("s1", "the tester signs in", role="setup", assertions=[]),
            f.step(
                "s2",
                "the tester places the order",
                role="test_step",
                assertions=[f.assertion("a1", "the confirmation appears")],
            ),
        ]
    )
    body = build_case(case, ProjectConfig())
    assert body["steps_type"] == "classic"
    assert [s["position"] for s in body["steps"]] == [1, 2]
    assert body["steps"][0]["expected_result"] == ""
    assert body["steps"][1]["expected_result"] == "the confirmation appears"


def test_qase_gherkin_mode_sends_the_scenario_without_our_front_matter(tmp_path: Path):
    from server.renderers.qase import build_case

    case = f.test_case(steps=[f.step("s1", "the tester signs in", assertions=[])])
    body = build_case(case, ProjectConfig(qase_steps="gherkin"))
    assert body["steps_type"] == "gherkin"
    assert "Scenario:" in body["steps"]
    # Our header comment and tag line are ours, not Qase's.
    assert "aitc-rem" not in body["steps"]
    assert not body["steps"].lstrip().startswith("@")


def test_a_generated_case_is_not_reported_as_automated(tmp_path: Path):
    # It is a manual test case until somebody automates it. Saying otherwise in
    # the tool of record would misreport the suite's coverage.
    from server.renderers.qase import build_case

    assert build_case(f.test_case(), ProjectConfig())["automation"] == 0


# --------------------------------------------------------------------------
# Xray (SS11) -- no exporter, because the .feature file is the format
# --------------------------------------------------------------------------


def test_the_xray_test_key_tag_is_off_unless_a_project_asks_for_it():
    # For everyone not using Xray it is a meaningless tag in a file they read.
    case = f.test_case(steps=[f.step("s1", "the tester signs in", assertions=[])])
    rendered = render_test_case(case, config=ProjectConfig())
    assert "@TEST_" not in rendered


def test_the_xray_test_key_tag_makes_a_re_import_update_rather_than_duplicate():
    case = f.test_case(steps=[f.step("s1", "the tester signs in", assertions=[])])
    rendered = render_test_case(case, config=ProjectConfig(xray_test_key="TR-142"))
    assert "@TEST_TR-142" in rendered
    # Idempotent whichever way the key is written in config.
    assert "@TEST_TEST_" not in render_test_case(
        case, config=ProjectConfig(xray_test_key="TEST_TR-142")
    )
