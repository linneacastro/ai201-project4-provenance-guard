"""Provenance Guard: Flask app.

The submission endpoint (POST /submit), the appeal endpoint (POST /appeal), a
health check (GET /health), and the audit log view (GET /log). /submit validates
the input, runs both detection signals (Groq in signals/llm.py, stylometry in
signals/stylometry.py), combines them with the confidence scorer (scoring.py)
into one attribution + confidence, maps that to a transparency label
(labels.py), saves a full audit record, and returns the result with a
content_id. Rate limiting (Flask-Limiter) sits in front of every route.
"""

import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit_log
from labels import label_for
from scoring import combine_signals
from signals.llm import classify_with_llm
from signals.stylometry import classify_with_stylometry

# Load GROQ_API_KEY (and anything else) from .env into the environment.
load_dotenv()

app = Flask(__name__)

# Input limit for /submit. "Not empty, not too long."
# 10,000 chars is roughly a long blog post or short-story excerpt, and it keeps
# each model call bounded. Tune this if real submissions need more room.
MAX_TEXT_CHARS = 10_000


def _rate_limit_key():
    """Rate-limit key: the creator_id when the platform sends it, else the IP.

    Keying on creator_id (planning.md, "Rate Limiting") means one creator's
    flood does not spend another creator's budget, and a client that omits it is
    still limited by IP. Reads the JSON body silently so it never errors the
    request it is guarding.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        creator_id = data.get("creator_id")
        if isinstance(creator_id, str) and creator_id.strip():
            return creator_id
    return get_remote_address()


# Rate limiting (planning.md, "Rate Limiting"). The cheap endpoints inherit the
# 30/minute default; /submit sets its own tighter limit below because every call
# spends a Groq request. In-memory storage is fine for a single-process demo; a
# real deployment would point storage_uri at Redis so limits are shared.
limiter = Limiter(
    _rate_limit_key,
    app=app,
    default_limits=["30 per minute"],
    storage_uri="memory://",
)


def _utc_now():
    """Current time as an ISO 8601 UTC string, e.g. 2026-06-28T18:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    """Submit text for attribution analysis.

    Validates the input, runs both detection signals, combines them into one
    attribution and confidence (0 to 1), maps that to a transparency label,
    saves a full audit record, and returns the result. Every response carries a
    content_id, which the audit log stores and the appeal endpoint looks up.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    text = data.get("text")

    # Validation: real text, a string, not empty, not too long.
    if text is None:
        return jsonify({"error": "Field 'text' is required."}), 400
    if not isinstance(text, str):
        return jsonify({"error": "Field 'text' must be a string."}), 400
    if not text.strip():
        return jsonify({"error": "Field 'text' must not be empty."}), 400
    if len(text) > MAX_TEXT_CHARS:
        return jsonify({
            "error": (
                f"Field 'text' is too long ({len(text)} chars). "
                f"Maximum is {MAX_TEXT_CHARS}."
            )
        }), 400

    # creator_id is optional. If sent, it must be a string. It is echoed back
    # and used for the audit log and rate-limit keying.
    creator_id = data.get("creator_id")
    if creator_id is not None and not isinstance(creator_id, str):
        return jsonify({
            "error": "Field 'creator_id' must be a string when provided."
        }), 400

    # Run both detection signals. Signal 1 (Groq) can fail; Signal 2 is pure
    # local math and always returns.
    try:
        llm = classify_with_llm(text)
    except Exception as exc:  # Groq down, a timeout, or a bad reply
        return jsonify({
            "error": "Detection signal failed. Please try again.",
            "detail": str(exc),
        }), 502

    stylometry = classify_with_stylometry(text)
    word_count = stylometry["metrics"].get("word_count", 0)

    # Combine both signals into one attribution + confidence (the M4 scorer).
    scored = combine_signals(llm, stylometry, word_count)
    attribution = scored["attribution"]
    confidence = scored["confidence"]

    # Map the attribution to its transparency label (labels.py). Because
    # attribution follows the confidence bands, the label tracks confidence: a
    # 0.51 result and a 0.95 result do not show the same words.
    label = label_for(attribution)

    content_id = str(uuid.uuid4())
    timestamp = _utc_now()

    # Audit entry: both signals in full, the combined result, the scoring
    # internals, the label variant, and an empty appeals list ready for /appeal.
    audit_log.append_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "text_snippet": text[:200],
        "attribution": attribution,
        "confidence": confidence,
        "label_variant": label["variant"],
        "signals": {
            "llm": {
                "verdict": llm["verdict"],
                "confidence": llm["confidence"],
                "reasoning": llm["reasoning"],
            },
            "stylometry": {
                "score": stylometry["score"],
                "verdict": stylometry["verdict"],
                "metrics": stylometry["metrics"],
            },
        },
        "scoring": {
            "direction": scored["direction"],
            "adj_ai": scored["adj_ai"],
            **scored["details"],
        },
        "status": "classified",
        "appeals": [],
    })

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": {
            "variant": label["variant"],
            "badge": label["badge"],
            "text": label["text"],
        },
        "signals": {
            "llm": {"verdict": llm["verdict"], "confidence": llm["confidence"]},
            "stylometry": {
                "verdict": stylometry["verdict"],
                "score": stylometry["score"],
            },
        },
        "creator_id": creator_id,
        "status": "classified",
        "timestamp": timestamp,
    }), 200


@app.post("/appeal")
def appeal():
    """Contest a classification.

    A creator sends the content_id from their /submit result plus their
    reasoning. We find that decision in the audit log, attach the appeal to it,
    and flip its status to "under_review" so the platform can step the label
    back while a person takes another look. Nothing is re-scored automatically
    (per planning.md, "Appeals Workflow").
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    content_id = data.get("content_id")
    # Input field is creator_reasoning (the creator's side, in their words).
    reason = data.get("creator_reasoning")

    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not isinstance(reason, str) or not reason.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required."}), 400

    timestamp = _utc_now()
    # Stored under "reason" to match the audit-log shape in planning.md.
    appeal_entry = {
        "appeal_id": str(uuid.uuid4()),
        "reason": reason,
        "timestamp": timestamp,
    }

    updated = audit_log.add_appeal(content_id, appeal_entry)
    if updated is None:
        return jsonify({
            "error": f"No decision found with content_id '{content_id}'."
        }), 404

    return jsonify({
        "appeal_id": appeal_entry["appeal_id"],
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal was received. This content is now under review.",
        "timestamp": timestamp,
    }), 200


@app.get("/health")
def health():
    """Cheap health check for monitoring.

    Confirms two critical parts are ready: the Groq API key is configured, and
    the audit log store is reachable (readable, with a writable directory). It
    does NOT call Groq (that would waste free quota and add latency). Returns
    503 if either part is down, so a monitoring tool can watch and alert.
    """
    key_present = bool(os.environ.get("GROQ_API_KEY"))
    log_ok = audit_log.is_healthy()
    healthy = key_present and log_ok
    body = {
        "status": "ok" if healthy else "error",
        "timestamp": _utc_now(),
        "checks": {
            "audit_log": "ok" if log_ok else "unavailable",
            "groq_api_key": "present" if key_present else "missing",
        },
    }
    return jsonify(body), (200 if healthy else 503)


@app.get("/log")
def get_log():
    """Return audit log entries as JSON.

    By default, newest first. Optional ?limit=N caps how many come back.
    Optional ?status=... filters (for example ?status=under_review for the
    review queue, which is sorted oldest-appeal-first so nothing sits
    forgotten). This endpoint is for documentation and grading visibility; a
    real system would put it behind auth.
    """
    entries = audit_log.read_all()  # oldest first, as stored

    status = request.args.get("status")
    if status:
        entries = [e for e in entries if e.get("status") == status]

    if status == "under_review":
        # Review queue: oldest appeal first, so nothing waits forgotten.
        entries = sorted(entries, key=_first_appeal_time)
    else:
        entries = list(reversed(entries))  # newest first

    limit = request.args.get("limit", type=int)
    if limit is not None and limit > 0:
        entries = entries[:limit]

    return jsonify({"entries": entries})


def _first_appeal_time(entry):
    """Sort key for the review queue: the time of the entry's first appeal."""
    appeals = entry.get("appeals") or []
    if appeals:
        return appeals[0].get("timestamp", "")
    return entry.get("timestamp", "")


if __name__ == "__main__":
    app.run(debug=True)
