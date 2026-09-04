"""Tests for app/activity_ref.py — the id<->token obfuscation used to keep
raw Mongo ObjectIds out of the browser (chat text and link hrefs alike)."""
import pytest

from app.activity_ref import deobfuscate_activity_id, obfuscate_activity_id

REAL_ID = "66f1a2b3c4d5e6f7a8b9c0d1"


def test_roundtrip_recovers_the_original_id():
    token = obfuscate_activity_id(REAL_ID)
    assert deobfuscate_activity_id(token) == REAL_ID


def test_token_does_not_look_like_the_real_id():
    token = obfuscate_activity_id(REAL_ID)
    assert token != REAL_ID
    assert REAL_ID not in token


def test_token_is_not_hex24_shaped():
    # Deliberate: StreamSanitizer's own id-detection regexes are `[a-fA-F0-9]{24}`.
    # If a token could ever collide with that shape, a later pass could mistake a
    # token for a raw id needing further stripping/tokenizing.
    token = obfuscate_activity_id(REAL_ID)
    assert len(token) != 24 or any(c not in "0123456789abcdefABCDEF" for c in token)


def test_same_id_always_produces_the_same_token():
    # Deterministic and stateless by design - no store/TTL to keep in sync, and
    # the same activity referenced twice in one reply (or across turns) gets a
    # consistent, recognizable token rather than a confusing new one each time.
    assert obfuscate_activity_id(REAL_ID) == obfuscate_activity_id(REAL_ID)


def test_different_ids_produce_different_tokens():
    other = "77a2b3c4d5e6f7a8b9c0d1e2"
    assert obfuscate_activity_id(REAL_ID) != obfuscate_activity_id(other)


def test_obfuscate_rejects_non_hex_input():
    with pytest.raises(ValueError):
        obfuscate_activity_id("not-a-valid-hex-id-at-all!")


def test_obfuscate_rejects_wrong_length_hex():
    with pytest.raises(ValueError):
        obfuscate_activity_id("abc123")  # valid hex, wrong length


@pytest.mark.parametrize("bad_token", [
    "",
    "not-a-real-token!!",
    "abc",  # too short to ever be a real token
    REAL_ID,  # a raw id passed where a token was expected - not garbage, but not
              # a valid base32 token shape either once decoded
])
def test_deobfuscate_returns_none_for_garbage_instead_of_raising(bad_token):
    assert deobfuscate_activity_id(bad_token) is None
