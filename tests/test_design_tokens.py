"""One palette, four surfaces, and nothing to keep them honest but this.

The review UI, the recorder popup, the mic permission page and the export page
each used to re-type the same hex values in their own stylesheet, and nine more
colours in the review UI bypassed even its own tokens. That is why dark mode
could not work: a theme can only swap what it can see, and a literal `#eef3f7`
sitting in a rule is invisible to it.

The two files cannot be one file -- an extension page cannot import across the
package boundary, and `dist/` is flat -- so the copy is deliberate and this test
is the drift check on it, the same shape as `schema/codegen.sh --check`.

If this fails: edit `ui/src/tokens.css`, then copy it to
`extension/src/styles/tokens.css`. Never the other way round, and never only
one of them.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = REPO_ROOT / "ui" / "src" / "tokens.css"
COPY = REPO_ROOT / "extension" / "src" / "styles" / "tokens.css"

#: Every stylesheet that is allowed to declare colour. Anything else naming a
#: hex is a colour the theme cannot reach.
THEMED = [
    REPO_ROOT / "ui" / "src" / "styles.css",
    REPO_ROOT / "extension" / "src" / "popup" / "popup.html",
    REPO_ROOT / "extension" / "src" / "offscreen" / "mic.html",
    REPO_ROOT / "extension" / "src" / "export" / "export.html",
]

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_the_two_palettes_are_the_same_file() -> None:
    assert CANONICAL.read_text(encoding="utf-8") == COPY.read_text(encoding="utf-8"), (
        "the extension's palette has drifted from the review UI's. Copy "
        "ui/src/tokens.css over extension/src/styles/tokens.css."
    )


def test_no_surface_declares_a_colour_of_its_own() -> None:
    """The rule that makes a theme possible at all.

    A hex here is not a style preference: it is a colour that stays put when
    the viewer is in dark mode, and one of them is enough to make a panel
    unreadable.
    """
    offenders = {
        path.relative_to(REPO_ROOT).as_posix(): sorted(set(HEX.findall(path.read_text("utf-8"))))
        for path in THEMED
        if HEX.search(path.read_text(encoding="utf-8"))
    }
    assert not offenders, f"colours declared outside tokens.css: {offenders}"


def test_every_token_is_defined_in_both_themes() -> None:
    """A token defined only in light is a hole in dark mode.

    It fails silently and looks like a rendering bug rather than a missing
    declaration, which is why it is worth asserting rather than reviewing.
    """
    text = CANONICAL.read_text(encoding="utf-8")
    blocks = text.split("@media (prefers-color-scheme: dark)")
    assert len(blocks) == 2, "expected exactly one dark-mode media query"

    def names(chunk: str) -> set[str]:
        return set(re.findall(r"(--[a-z0-9-]+)\s*:", chunk))

    light = names(blocks[0])
    dark = names(blocks[1])

    # Scales and fonts do not change with the theme; only colour does. What must
    # be complete is the set the dark block chooses to redefine -- every one of
    # them has to exist in light, or it is overriding nothing.
    assert dark <= light, f"dark mode defines tokens light never declares: {sorted(dark - light)}"

    # And the explicit toggle has to match what the media query does, or the
    # theme differs depending on how the viewer arrived at it.
    explicit = names(text.split(':root[data-theme="dark"]')[1])
    assert explicit == dark, (
        "the [data-theme=dark] block and the prefers-color-scheme block disagree: "
        f"{sorted(explicit ^ dark)}"
    )
