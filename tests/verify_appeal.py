"""Check POST /appeal: it updates status and logs the appeal correctly.

Drives the endpoint through Flask's test client against a THROWAWAY log file,
so the real audit_log.json is never touched. Seeds one classified decision,
appeals it, and confirms:
  - 200 with the confirmation shape,
  - the decision's status flips to "under_review",
  - the appeal is stored next to the original decision (reason + appeal_id),
  - a second appeal appends rather than replaces,
  - bad content_id -> 404, missing fields -> 400.

No Groq call (only /appeal is exercised). Run from the project root:
    .venv/bin/python tests/verify_appeal.py
"""

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import audit_log  # noqa: E402

# Point the store at a throwaway path before the app uses it. _read_all and
# _write_all read this module global on every call, so the override sticks
# everywhere, including inside app.audit_log (the same module object).
_fd, _TMP = tempfile.mkstemp(suffix=".json", prefix="verify_appeal_")
os.close(_fd)
os.remove(_TMP)  # start empty; a missing file means "no entries"
audit_log.LOG_PATH = _TMP

import app as app_module  # noqa: E402

client = app_module.app.test_client()

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def main():
    # Seed one classified decision, no appeals yet.
    audit_log.append_entry({
        "content_id": "seed-123",
        "creator_id": "seed-writer",
        "timestamp": "2026-06-30T00:00:00Z",
        "text_snippet": "A seeded decision for the appeal test.",
        "attribution": "likely_ai",
        "confidence": 0.88,
        "status": "classified",
    })

    print("########## POST /appeal (happy path) ##########")
    resp = client.post("/appeal", json={
        "content_id": "seed-123",
        "creator_reasoning": "I wrote this myself from personal experience.",
    })
    body = resp.get_json()
    print(f"  HTTP {resp.status_code}: {body}\n")
    check(resp.status_code == 200, f"happy path expected 200, got {resp.status_code}")
    check(body.get("status") == "under_review", "response status not under_review")
    check(bool(body.get("appeal_id")), "response missing appeal_id")
    check(bool(body.get("message")), "response missing message")

    # The log entry must now be under_review with the appeal attached to it.
    entry = next(e for e in audit_log.read_all() if e["content_id"] == "seed-123")
    print("########## Log entry after appeal ##########")
    print(f"  status : {entry.get('status')}")
    print(f"  appeals: {entry.get('appeals')}\n")
    check(entry.get("status") == "under_review", "log entry status not flipped")
    appeals = entry.get("appeals", [])
    check(len(appeals) == 1, f"expected 1 appeal logged, got {len(appeals)}")
    if appeals:
        a = appeals[0]
        check(a.get("reason") == "I wrote this myself from personal experience.",
              "stored reason does not match input creator_reasoning")
        check(bool(a.get("appeal_id")), "stored appeal missing appeal_id")
        check(bool(a.get("timestamp")), "stored appeal missing timestamp")

    print("########## Second appeal appends (does not replace) ##########")
    client.post("/appeal", json={
        "content_id": "seed-123",
        "creator_reasoning": "Adding my draft history as extra evidence.",
    })
    entry = next(e for e in audit_log.read_all() if e["content_id"] == "seed-123")
    print(f"  appeals now: {len(entry.get('appeals', []))}\n")
    check(len(entry.get("appeals", [])) == 2, "second appeal did not append")

    print("########## Error paths ##########")
    r404 = client.post("/appeal", json={
        "content_id": "does-not-exist", "creator_reasoning": "x",
    })
    print(f"  bad content_id      -> HTTP {r404.status_code} (want 404)")
    check(r404.status_code == 404, f"bad content_id expected 404, got {r404.status_code}")

    r_no_reason = client.post("/appeal", json={"content_id": "seed-123"})
    print(f"  missing reasoning   -> HTTP {r_no_reason.status_code} (want 400)")
    check(r_no_reason.status_code == 400, f"missing reason expected 400, got {r_no_reason.status_code}")

    r_no_id = client.post("/appeal", json={"creator_reasoning": "x"})
    print(f"  missing content_id  -> HTTP {r_no_id.status_code} (want 400)\n")
    check(r_no_id.status_code == 400, f"missing content_id expected 400, got {r_no_id.status_code}")

    print("########## Result ##########")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("  PASS: /appeal updates status and logs the appeal correctly.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        if os.path.exists(_TMP):
            os.remove(_TMP)
    sys.exit(code)
