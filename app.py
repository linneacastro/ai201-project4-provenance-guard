"""Provenance Guard: Flask app.

The submission endpoint (POST /submit), a health check (GET /health), and the
audit log view (GET /log). /submit validates the input, runs both detection
signals (Groq in signals/llm.py, stylometry in signals/stylometry.py), combines
them with the confidence scorer (scoring.py) into one attribution + confidence,
saves a full audit record, and returns the result with a content_id. The
transparency label is still a placeholder until the label logic (M5).
"""

import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import audit_log
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


def _utc_now():
    """Current time as an ISO 8601 UTC string, e.g. 2026-06-28T18:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.post("/submit")
def submit():
    """Submit text for attribution analysis.

    Validates the input, runs both detection signals, combines them into one
    attribution and confidence (0 to 1), saves a full audit record, and returns
    the result. The transparency label is still a placeholder until M5. Every
    response carries a content_id, which the audit log stores and the appeal
    endpoint looks up.
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
    # now and used later for the audit log and rate-limit keying.
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

    content_id = str(uuid.uuid4())
    timestamp = _utc_now()

    # Audit entry: both signals in full, plus the combined result and the
    # scoring internals. The label variant is still a placeholder (M5).
    audit_log.append_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "text_snippet": text[:200],
        "attribution": attribution,
        "confidence": confidence,
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
    })

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": "Placeholder label. Final transparency wording comes in M5.",
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


@app.get("/health")
def health():
    """Cheap health check for monitoring.

    Confirms the Groq API key is configured. It does NOT call Groq (that would
    waste free quota and add latency). The audit-log check is added in
    Milestone 5, when the log store exists.
    """
    key_present = bool(os.environ.get("GROQ_API_KEY"))
    body = {
        "status": "ok" if key_present else "error",
        "timestamp": _utc_now(),
        "checks": {
            "groq_api_key": "present" if key_present else "missing",
        },
    }
    return jsonify(body), (200 if key_present else 503)


@app.get("/log")
def get_log():
    """Return audit log entries as JSON, newest first.

    Optional ?limit=N caps how many entries come back (handy for showing just
    the most recent ones). This endpoint is for documentation and grading
    visibility; a real system would put it behind auth.
    """
    entries = list(reversed(audit_log.read_all()))  # newest first

    limit = request.args.get("limit", type=int)
    if limit is not None and limit > 0:
        entries = entries[:limit]

    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(debug=True)
