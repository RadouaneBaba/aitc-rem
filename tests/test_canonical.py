"""If this drifts, evidence_retrieved starts rejecting true assertions."""

from __future__ import annotations

import json

import pytest

from server.util.canonical import canonical_json, response_hash


def test_key_order_does_not_change_the_hash():
    a = {"literal": "Order confirmed", "eventId": "evt_027", "kind": "semantic_node"}
    b = {"kind": "semantic_node", "eventId": "evt_027", "literal": "Order confirmed"}
    assert response_hash(a) == response_hash(b)


def test_round_trip_through_disk_is_stable():
    # The exact path evidence_retrieved takes: hash, write, read back, re-hash.
    value = {"nodes": [{"role": "alert", "name": "Order confirmed"}], "n": 1}
    first = response_hash(value)
    reloaded = json.loads(canonical_json(value))
    assert response_hash(reloaded) == first


def test_non_ascii_survives_unescaped_and_stably():
    value = {"name": "Réservé — 500 €", "note": "日本語"}
    text = canonical_json(value)
    assert "Réservé" in text  # not \u-escaped
    assert response_hash(json.loads(text)) == response_hash(value)


def test_nan_is_refused_rather_than_written_as_invalid_json():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_distinct_values_hash_differently():
    assert response_hash({"literal": "Order confirmed"}) != response_hash(
        {"literal": "Order  confirmed"}
    )
