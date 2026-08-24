"""The step library (SS12) -- approved phrasing, remembered across runs.

    "The number-one reason generated-Gherkin tools get abandoned. Ten testers
     record ten sessions and you get ten phrasings of one action."

This is also the project's memory. A step enters it because a **human approved
it** in review (SS12.2), never because a model produced it -- which makes the
library a record of accepted work rather than an average of generated work. Two
recordings of the same login then come out phrased identically, and the same
step definition matches both.

Deliberately lexical, not semantic. The question here is "have we said almost
exactly this before", not "is this about the same topic": we want to reuse
*wording*, and near-duplicate matching is the correct semantics for that.
`rapidfuzz` does it with no dependencies of its own, deterministically, and with
a score you can explain to somebody. Embeddings would answer a question nobody
asked, cost multiple gigabytes, and make a run unreproducible when the model
file changes underneath it.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rapidfuzz import fuzz, process

#: Reuse the stored wording verbatim at or above this. Chosen high on purpose:
#: rewriting a step to phrasing that means something slightly different is worse
#: than two steps that read a little differently.
REUSE_THRESHOLD = 90.0

#: Worth showing a reviewer as "you have said something like this before", but
#: not worth substituting automatically.
SUGGEST_THRESHOLD = 75.0

DEFAULT_PROJECT = "local"


@dataclass(frozen=True)
class LibraryEntry:
    """One approved step."""

    id: str
    text: str
    role: str | None
    project: str
    approved_at: str
    recording_id: str | None = None
    run_id: str | None = None
    uses: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "role": self.role,
            "approvedAt": self.approved_at,
            "uses": self.uses,
        }


@dataclass(frozen=True)
class Match:
    """An approved step that resembles the one being drafted."""

    entry: LibraryEntry
    score: float
    #: The drafted text, kept so `reuse` can compare meaning rather than only
    #: similarity.
    query: str = ""

    @property
    def reuse(self) -> bool:
        """Is this close enough, and safe enough, to recommend reusing verbatim?

        A recommendation to the naming stage, never an automatic substitution.
        The pipeline does not rewrite steps behind a model's back, for a reason
        the fixtures make concrete: "adds a widget to the cart" scores 95
        against the approved "adds a Blue Widget to the cart", and swapping them
        would add a fact the recording may not support. Only something looking
        at the evidence can tell whether the widget really was blue -- so the
        library offers, the model decides, and `library_verbatim` checks that
        whatever claimed reuse actually matches.

        Score alone is not even enough to *recommend*. "places the order" and
        "places the order again" score 95 and are different steps -- the second
        is what naming writes precisely to mark a deliberate repeat. So a high
        score is vetoed unless the two sentences quote the same values and carry
        the same meaning-bearing modifiers.
        """
        if self.score < REUSE_THRESHOLD:
            return False
        return not self.query or _same_meaning(self.query, self.entry.text)

    def as_dict(self) -> dict[str, object]:
        return {
            **self.entry.as_dict(),
            "score": round(self.score, 1),
            "reuse": self.reuse,
        }


SCHEMA = """
CREATE TABLE IF NOT EXISTS steps (
    id           TEXT PRIMARY KEY,
    project      TEXT NOT NULL,
    text         TEXT NOT NULL,
    role         TEXT,
    recording_id TEXT,
    run_id       TEXT,
    approved_at  TEXT NOT NULL,
    uses         INTEGER NOT NULL DEFAULT 1,
    UNIQUE (project, text)
);
"""


class StepLibrary:
    """Approved step phrasing for one project, on disk.

    SQLite because it is in the standard library, the whole store is a single
    file somebody can copy between machines, and at the scale this operates on
    -- hundreds of short sentences -- reading every row and scoring it in memory
    is faster than any index would be.
    """

    def __init__(self, path: Path | str, *, project: str = DEFAULT_PROJECT) -> None:
        self.path = Path(path)
        self.project = project
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------

    def entries(self) -> list[LibraryEntry]:
        rows = self._db.execute(
            "SELECT * FROM steps WHERE project = ? ORDER BY uses DESC, approved_at DESC",
            (self.project,),
        ).fetchall()
        return [_entry(row) for row in rows]

    def get(self, entry_id: str) -> LibraryEntry | None:
        row = self._db.execute("SELECT * FROM steps WHERE id = ?", (entry_id,)).fetchone()
        return _entry(row) if row else None

    def add(
        self,
        text: str,
        *,
        role: str | None = None,
        recording_id: str | None = None,
        run_id: str | None = None,
    ) -> LibraryEntry | None:
        """Record an approved step. Re-approving the same wording counts a use.

        Use counts are not decoration: when two entries score alike, the one
        more teams have already accepted is the better one to converge on.
        """
        text = " ".join((text or "").split())
        if not text:
            return None

        existing = self._db.execute(
            "SELECT * FROM steps WHERE project = ? AND text = ?", (self.project, text)
        ).fetchone()
        if existing:
            self._db.execute("UPDATE steps SET uses = uses + 1 WHERE id = ?", (existing["id"],))
            self._db.commit()
            return self.get(existing["id"])

        # Content-addressed, and NOT with builtin hash(): string hashing is
        # salted per process, so the same approved step would get a different
        # id in every run and `libraryRef` would stop resolving across the
        # session boundary the library exists to cross.
        digest = hashlib.sha256((self.project + chr(0) + text).encode()).hexdigest()
        entry_id = f"lib_{digest[:16]}"
        self._db.execute(
            "INSERT INTO steps (id, project, text, role, recording_id, run_id, approved_at, uses)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (
                entry_id,
                self.project,
                text,
                role,
                recording_id,
                run_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._db.commit()
        return self.get(entry_id)

    def add_many(self, texts: Iterable[str], **kw: object) -> int:
        return sum(1 for t in texts if self.add(t, **kw) is not None)  # type: ignore[arg-type]

    # ------------------------------------------------------------------

    def search(self, query: str, *, limit: int = 5) -> list[Match]:
        """Closest approved phrasings, best first.

        Scored on the sentence with the voice prefix removed. Every step in a
        project starts "the tester ", so leaving it in gives every pair a long
        identical head: measured on the real fixtures, "signs in" scored 85
        against "adds a Blue Widget to the cart", which is not a similarity, it
        is a shared prefix. Stripped, the same pair scores 34.

        `WRatio` rather than plain ratio because it tolerates the partial and
        reordered cases that are genuinely the same step worded differently.
        """
        query = " ".join((query or "").split())
        entries = self.entries()
        if not query or not entries:
            return []

        found = process.extract(
            _comparable(query),
            [_comparable(e.text) for e in entries],
            scorer=fuzz.WRatio,
            score_cutoff=SUGGEST_THRESHOLD,
            limit=limit,
        )
        return [
            Match(entry=entries[index], score=score, query=query) for _text, score, index in found
        ]

    def exact(self, text: str) -> LibraryEntry | None:
        """The entry this text *is*, ignoring only spacing.

        What sets `libraryRef`. Exact rather than fuzzy on purpose: the claim
        being recorded is "this step reuses approved wording", and
        `library_verbatim` rejects a step that claims reuse and was then
        rewritten. A fuzzy match here would make that validator meaningless.
        """
        text = " ".join((text or "").split())
        if not text:
            return None
        row = self._db.execute(
            "SELECT * FROM steps WHERE project = ? AND text = ?", (self.project, text)
        ).fetchone()
        return _entry(row) if row else None


#: Stripped before scoring. Carried by every step in a project, so it inflates
#: every comparison without telling you anything.
VOICES = ("the tester ", "the user ", "the admin ", "the customer ", "i ")

#: Words that change what a step claims. A sentence that has one and a sentence
#: that does not are different steps however similar they look.
MODIFIERS = frozenset(
    {
        "again",
        "not",
        "no",
        "without",
        "invalid",
        "expired",
        "empty",
        "second",
        "twice",
        "fails",
        "failed",
        "cannot",
        "unable",
        "wrong",
        "incorrect",
        "duplicate",
        "missing",
    }
)

QUOTED = re.compile(r"\"([^\"]*)\"|'([^']*)'")
WORD = re.compile(r"[a-z0-9_]+")


def _comparable(text: str) -> str:
    """The part of a step sentence worth scoring."""
    lowered = " ".join((text or "").split()).casefold()
    for voice in VOICES:
        if lowered.startswith(voice):
            return lowered[len(voice) :]
    return lowered


def _significant(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """The two things that must match exactly: quoted values and modifiers."""
    lowered = " ".join((text or "").split()).casefold()
    values = frozenset(a or b for a, b in QUOTED.findall(lowered) if (a or b))
    modifiers = frozenset(w for w in WORD.findall(lowered) if w in MODIFIERS)
    return values, modifiers


def _same_meaning(a: str, b: str) -> bool:
    return _significant(a) == _significant(b)


def _entry(row: sqlite3.Row) -> LibraryEntry:
    return LibraryEntry(
        id=row["id"],
        text=row["text"],
        role=row["role"],
        project=row["project"],
        approved_at=row["approved_at"],
        recording_id=row["recording_id"],
        run_id=row["run_id"],
        uses=row["uses"],
    )


__all__ = [
    "DEFAULT_PROJECT",
    "REUSE_THRESHOLD",
    "SUGGEST_THRESHOLD",
    "LibraryEntry",
    "Match",
    "StepLibrary",
]
