import time

from app import token_store


def test_set_get_roundtrip():
    token_store.set_token("sess-1", "jwt-abc")
    assert token_store.get_token("sess-1") == "jwt-abc"


def test_missing_and_none_session():
    assert token_store.get_token("nope") is None
    assert token_store.get_token(None) is None
    token_store.set_token(None, "x")  # no-op, must not raise
    token_store.set_token("s", None)  # no-op


def test_expiry(monkeypatch):
    real_time = time.time  # capture before patching to avoid self-recursion
    token_store.set_token("sess-exp", "jwt")
    # Fast-forward past the TTL.
    monkeypatch.setattr(token_store.time, "time", lambda: real_time() + token_store.TTL_SECONDS + 1)
    assert token_store.get_token("sess-exp") is None


def test_extract_token_shapes():
    assert token_store.extract_token('{"authToken": "t1"}') == "t1"
    assert token_store.extract_token('{"data": {"authToken": "t2"}}') == "t2"
    assert token_store.extract_token('{"success": true, "token": "t3"}') == "t3"
    assert token_store.extract_token('{"success": false}') is None
    assert token_store.extract_token("not json") is None


# --- verified phone (send_otp -> verify_otp handoff) ------------------


def test_extract_phone_scans_common_key_names():
    assert token_store.extract_phone('{"phone": "+911234567890"}') == "+911234567890"
    assert token_store.extract_phone('{"phoneNumber": "+911234567890"}') == "+911234567890"
    assert token_store.extract_phone('{"mobile": "+911234567890"}') == "+911234567890"
    assert token_store.extract_phone('{"otp": "1234"}') is None  # no phone-shaped key
    assert token_store.extract_phone(None) is None
    assert token_store.extract_phone("not json") is None


def test_pending_phone_roundtrip_and_pop_once():
    token_store.set_pending_phone("sess-p", "+911234567890")
    assert token_store.pop_pending_phone("sess-p") == "+911234567890"
    assert token_store.pop_pending_phone("sess-p") is None  # popped, not peeked


def test_pending_phone_missing_and_none_session():
    assert token_store.pop_pending_phone("nope") is None
    assert token_store.pop_pending_phone(None) is None
    token_store.set_pending_phone(None, "x")     # no-op, must not raise
    token_store.set_pending_phone("s", None)     # no-op


def test_pending_phone_expiry(monkeypatch):
    real_time = time.time
    token_store.set_pending_phone("sess-p-exp", "+911234567890")
    monkeypatch.setattr(token_store.time, "time", lambda: real_time() + token_store.TTL_SECONDS + 1)
    assert token_store.pop_pending_phone("sess-p-exp") is None
