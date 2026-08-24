"""Import a Chrome DevTools Recorder JSON as a recording.

Chrome's built-in Recorder panel exports a JSON of typed steps, and each step
carries a *ranked list* of selector strategies -- including `aria/Name`, which is
an accessible-name selector. That is close enough to this project's own primary
key (role plus accessible name) that the mapping is near-lossless in the
direction that matters, and the whole importer is JSON parsing with no
dependency.

Worth having because it lets a team bring recordings they already made, and
because Chrome's Recorder is the closest thing to prior art for the capture
layer.

**What it cannot bring is the point.** A DevTools recording has no network
calls, no console, no DOM snapshots and no screenshots. So an imported recording
carries a strictly weaker evidence set, and a whole class of assertion becomes
inadmissible -- there is nothing for `find_text` to index and therefore nothing
a claim could cite. That is the admissibility rule working exactly as designed,
not a gap to paper over, and `import_devtools` says so in the fidelity flags
rather than degrading quietly.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from server.models import Recording

#: Chrome's step types, mapped to ours. `setViewport` and `navigate` bracket a
#: recording rather than describing intent; the rest are actions a tester took.
STEP_TYPES = {
    "click": "click",
    "doubleClick": "click",
    "change": "input",
    "keyDown": "keydown",
    "hover": "click",
    "navigate": "navigate",
}

#: SS7.1 applied to an import. Redaction normally happens in the browser before
#: anything is persisted, and Chrome's Recorder does no such thing -- it writes
#: whatever was typed, including passwords, straight into the JSON. Importing
#: that verbatim would put a plaintext secret on disk through a path the rule
#: exists to make impossible, so it is redacted here, before the recording is
#: constructed.
#:
#: Deliberately conservative and pattern-based, the same categories the recorder
#: handles. It cannot match the browser version -- there is no DOM to ask
#: whether a field was `type=password`, only the accessible name -- so the
#: import is flagged and the tester is told to check.
SECRET_FIELD = re.compile(r"password|passcode|secret|token|api[ _-]?key|cvv|pin", re.IGNORECASE)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CARD = re.compile(r"^[\d ]{13,23}$")

#: Chrome prefixes each selector with its strategy. `aria/` is the interesting
#: one: it is an accessible-name selector, which is what this project keys on.
ARIA = re.compile(r"^aria/(.*)$")
TEXT = re.compile(r"^text/(.*)$")
XPATH = re.compile(r"^(?:xpath|pierce)/(.*)$")


def import_devtools(
    document: dict[str, Any],
    *,
    recording_id: str | None = None,
    project_id: str = "local",
    owner_id: str = "local",
) -> Recording:
    """Turn a Recorder export into a `Recording` this pipeline can run."""
    title = str(document.get("title") or "imported recording")
    raw_steps = [s for s in document.get("steps", []) if isinstance(s, dict)]

    start_url = next(
        (str(s.get("url")) for s in raw_steps if s.get("type") == "navigate" and s.get("url")),
        "",
    )

    events: list[dict[str, Any]] = []
    origins: list[str] = []
    parameters: dict[str, dict[str, Any]] = {}
    url = start_url
    for step in raw_steps:
        kind = STEP_TYPES.get(str(step.get("type")))
        if kind == "navigate":
            url = str(step.get("url") or url)
            _remember(origins, url)
            continue
        if kind is None:
            continue

        role, name, selectors = _target(step)
        index = len(events)
        # Chrome records no timing, so the order is all there is. Spaced past
        # the idle-gap threshold on purpose: without real timestamps the
        # segmenter has no evidence for grouping, and inventing closeness would
        # manufacture step boundaries nobody observed.
        timestamp = float(index * 3000)
        events.append(
            {
                "id": f"evt_{index + 1:03d}",
                "seq": index,
                "timestamp": timestamp,
                "type": kind,
                "url": url,
                "target": {
                    "role": role,
                    "name": name,
                    "tagName": "",
                    "selectors": selectors,
                    "frame": [],
                    **(
                        {"value": _redact(str(step.get("value")), name, parameters)}
                        if step.get("value")
                        else {}
                    ),
                },
                "before": _snapshot(url, title, timestamp),
                "after": _snapshot(url, title, timestamp + 100),
                "diff": {"added": [], "removed": [], "changed": []},
                "network": [],
                "console": [],
                # SS6.8 -- degrade loudly. Every one of these is true of an
                # imported recording and none of them is recoverable, so a
                # reader learns why an assertion could not be made rather than
                # wondering.
                "fidelity": ["network_incomplete", "no_accessible_name"]
                if not name
                else ["network_incomplete"],
            }
        )

    _remember(origins, start_url)
    now = datetime.now(UTC)
    return Recording.model_validate(
        {
            "schemaVersion": "1.0",
            "id": recording_id or f"rec_import_{int(now.timestamp())}",
            "projectId": project_id,
            "ownerId": owner_id,
            "createdAt": now.isoformat(),
            "objective": title,
            "metadata": {
                "capturedAt": now.isoformat(),
                "durationMs": float(len(events) * 3000),
                "browser": "Chrome DevTools Recorder",
                "userAgent": "chrome-devtools-recorder",
                "viewport": _viewport(raw_steps),
                "startUrl": start_url,
                "origins": origins,
                "recorderVersion": "import",
                "fidelitySummary": {"network_incomplete": len(events)},
            },
            "events": events,
            "narration": [],
            "annotations": [],
            "parameters": list(parameters.values()),
        }
    )


def _redact(value: str, field_name: str, parameters: dict[str, dict[str, Any]]) -> str:
    """Replace a secret-shaped value with a placeholder, and record it (SS7.2).

    The replacement is not damage control -- a placeholder is more useful than
    the value it replaces, because whoever runs the test supplies their own.
    """
    if SECRET_FIELD.search(field_name or ""):
        return _placeholder("password", "password", value, parameters)
    if EMAIL.match(value.strip()):
        return _placeholder("user_email_1", "email", value, parameters)
    if CARD.match(value.strip()) and _luhn(re.sub(r"\D", "", value)):
        return _placeholder("card_number", "card", value, parameters)
    return value


def _placeholder(name: str, category: str, raw: str, parameters: dict[str, dict[str, Any]]) -> str:
    entry = parameters.setdefault(
        name,
        {"name": name, "placeholder": f"<<{name}>>", "category": category, "occurrences": 0},
    )
    entry["occurrences"] += 1
    del raw
    return f"<<{name}>>"


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for char in reversed(digits):
        n = int(char)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return bool(digits) and total % 10 == 0


def _target(step: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    """Chrome's ranked selector list, in this project's vocabulary.

    `selectors` is an array *of arrays* -- several independent strategies for
    the same element, which is the same idea as `SelectorSet` and the reason the
    import is worth doing at all.
    """
    flat: list[str] = []
    for group in step.get("selectors") or []:
        if isinstance(group, list):
            flat.extend(str(s) for s in group)
        elif isinstance(group, str):
            flat.append(group)

    name = ""
    selectors: dict[str, str] = {}
    for candidate in flat:
        aria = ARIA.match(candidate)
        text = TEXT.match(candidate)
        if aria and not name:
            name = aria.group(1).strip()
        elif text and "text" not in selectors:
            selectors["text"] = text.group(1).strip()
        elif not XPATH.match(candidate) and "css" not in selectors:
            selectors["css"] = candidate

    # `css` is the only required member of a SelectorSet, and an xpath-only step
    # would otherwise fail validation for a reason nobody could act on.
    selectors.setdefault("css", flat[0] if flat else "body")
    # Chrome records the accessible NAME but not the role, so no `role` selector
    # is emitted at all. `getByRole('', { name: ... })` would be a selector that
    # cannot resolve, and a fallback chain containing one is worse than a shorter
    # chain -- the replay would spend a timeout on it before moving on. The name
    # is not lost: it lands on `target.name`, which is what the naming stage
    # actually reads.
    return "", name, selectors


def _snapshot(url: str, title: str, at: float) -> dict[str, Any]:
    """A snapshot with no nodes in it -- which is the honest shape.

    Chrome captured no DOM, so there is nothing for `find_text` to index and no
    assertion about page content can be grounded. Emitting an empty snapshot
    rather than omitting one keeps every downstream stage working on the
    structure it expects, while giving them nothing to cite.
    """
    return {
        "capturedAt": at,
        "url": url,
        "title": title,
        # `scoped` because that is what the schema allows and it is the truthful
        # one: nothing was captured, which is a scope of nothing.
        "scope": "scoped",
        "root": {"ref": "imported.0", "role": "document", "name": title, "children": []},
        "liveRegions": [],
    }


def _viewport(steps: list[dict[str, Any]]) -> dict[str, int]:
    for step in steps:
        if step.get("type") == "setViewport":
            return {"w": int(step.get("width") or 1280), "h": int(step.get("height") or 720)}
    return {"w": 1280, "h": 720}


def _remember(origins: list[str], url: str) -> None:
    if not url:
        return
    match = re.match(r"^(https?://[^/]+)", url)
    if match and match.group(1) not in origins:
        origins.append(match.group(1))


__all__ = ["import_devtools"]
