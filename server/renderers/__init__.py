"""Renderers over the IR (SS11).

    "One IR, three renderers. No format is second-class, and a fourth output
     means writing a renderer, not touching the pipeline."

Gherkin and its evidence sidecar are always produced -- the validation gate
reads the rendered feature, so it is not optional. Excel and Jira are opt-in per
project, because a team that lives in one of them does not want the other two
cluttering the run directory.
"""

from __future__ import annotations

from pathlib import Path

from server.config import ProjectConfig
from server.models import IRDocument
from server.renderers.base import Exporter, ExportResult, case_stem, review_warnings
from server.renderers.jira import JiraExporter
from server.renderers.qase import QaseExporter
from server.renderers.xlsx import ExcelExporter

#: Formats a project can ask for by name in `config/project.yaml`.
EXPORTERS: dict[str, type] = {
    ExcelExporter.name: ExcelExporter,
    JiraExporter.name: JiraExporter,
    QaseExporter.name: QaseExporter,
}


def export_all(
    ir: IRDocument,
    *,
    out_dir: Path,
    config: ProjectConfig,
    names: list[str] | None = None,
) -> list[ExportResult]:
    """Run the requested exporters. Unknown names are reported, not ignored.

    A typo in a config file that silently produces no spreadsheet is worse than
    an error: the tester finds out when they go looking for the file.
    """
    wanted = [n.strip().lower() for n in (names if names is not None else config.exports)]
    results: list[ExportResult] = []

    for name in dict.fromkeys(wanted):
        exporter = EXPORTERS.get(name)
        if exporter is None:
            results.append(
                ExportResult(
                    exporter=name,
                    warnings=[
                        f"no exporter called {name!r}; available: {', '.join(sorted(EXPORTERS))}"
                    ],
                )
            )
            continue
        results.append(exporter().export(ir, out_dir=out_dir, config=config))

    return results


__all__ = [
    "EXPORTERS",
    "ExcelExporter",
    "ExportResult",
    "Exporter",
    "JiraExporter",
    "case_stem",
    "export_all",
    "review_warnings",
]
