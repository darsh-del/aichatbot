"""Tests for app/activity_ref.py — small reference numbers standing in for
catalog activity ids, so the raw Mongo ObjectId never reaches the browser."""
import pytest

from app import activity_ref
from app.activity_ref import get_or_create_ref, resolve_ref

REAL_ID = "66f1a2b3c4d5e6f7a8b9c0d1"
OTHER_ID = "77a2b3c4d5e6f7a8b9c0d1e2"


@pytest.fixture(autouse=True)
def _reset_ref_tables():
    # State is a plain in-memory dict (see the module docstring) - reset it
    # between tests so one test's refs can't leak into another's assumptions.
    activity_ref._id_to_ref.clear()
    activity_ref._ref_to_id.clear()
    activity_ref._next_ref = 1
    yield


def test_roundtrip_recovers_the_original_id():
    ref = get_or_create_ref(REAL_ID)
    assert resolve_ref(ref) == REAL_ID


def test_ref_does_not_look_like_the_real_id():
    ref = get_or_create_ref(REAL_ID)
    assert ref != REAL_ID
    assert REAL_ID not in ref


def test_ref_is_not_hex24_shaped():
    # Deliberate: StreamSanitizer's own id-detection regexes are `[a-fA-F0-9]{24}`.
    # If a ref could ever collide with that shape, a later pass could mistake it
    # for a raw id needing further stripping/replacing.
    ref = get_or_create_ref(REAL_ID)
    assert len(ref) != 24 or any(c not in "0123456789abcdefABCDEF" for c in ref)


def test_same_id_always_returns_the_same_ref():
    # The same activity referenced twice in one reply (or across turns) must
    # get a consistent, recognizable ref rather than a confusing new one.
    first = get_or_create_ref(REAL_ID)
    second = get_or_create_ref(REAL_ID)
    assert first == second


def test_different_ids_get_different_refs():
    assert get_or_create_ref(REAL_ID) != get_or_create_ref(OTHER_ID)


def test_refs_are_handed_out_in_order():
    # Not load-bearing behavior by itself, but backs up the "small opaque
    # counter" design claim - these should read as plainly sequential, not
    # some encoded/derived value.
    first = get_or_create_ref(REAL_ID)
    second = get_or_create_ref(OTHER_ID)
    assert int(second) == int(first) + 1


def test_get_or_create_ref_rejects_non_hex_input():
    with pytest.raises(ValueError):
        get_or_create_ref("not-a-valid-hex-id-at-all!")


def test_get_or_create_ref_rejects_wrong_length_hex():
    with pytest.raises(ValueError):
        get_or_create_ref("abc123")  # valid hex, wrong length


@pytest.mark.parametrize("bad_ref", [
    "",
    "not-a-real-ref!!",
    "999999",  # well-formed but never handed out
    REAL_ID,   # a raw id passed where a ref was expected
])
def test_resolve_ref_returns_none_for_unknown_ref_instead_of_raising(bad_ref):
    assert resolve_ref(bad_ref) is None
