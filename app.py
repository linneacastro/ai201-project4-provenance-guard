"""Provenance Guard: Flask app.

Milestone 3: the submission endpoint (POST /submit) and a health check
(GET /health). /submit validates the input, runs the first detection signal
(Groq), and returns a result with a content_id. The confidence score and the
label are placeholders until the scorer (M4) and the label logic (M5) are
built. The first signal lives in signals/llm.py.
"""

import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import audit_log
from signals.llm import classify_with_llm

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

    Milestone 3: validates the input, runs the first detection signal (Groq),
    and returns a result. The confidence score and the label are placeholders
    until the scorer (M4) and the label logic (M5) are built. Every response
    carries a content_id, which the audit log stores and the appeal endpoint
    looks up.
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

    # Run the first detection signal (Groq). One signal for now; the second
    # signal and the real confidence scorer arrive in M4.
    try:
        llm = classify_with_llm(text)
    except Exception as exc:  # Groq down, a timeout, or a bad reply
        return jsonify({
            "error": "Detection signal failed. Please try again.",
            "detail": str(exc),
        }), 502

    # Placeholder mapping from signal 1's verdict to an attribution. The real
    # attribution (including the "uncertain" band) is decided by the M4 scorer.
    attribution = "likely_ai" if llm["verdict"] == "ai" else "likely_human"

    content_id = str(uuid.uuid4())
    timestamp = _utc_now()

    # Write a structured audit entry for this decision before responding.
    # Milestone 4 extends each entry with the second signal and combined score.
    audit_log.append_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": llm["confidence"],   # placeholder until the M4 scorer
        "llm_score": llm["confidence"],    # signal 1's score
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,        # from signal 1 only (placeholder)
        "confidence": llm["confidence"],   # placeholder: signal 1's own confidence
        "label": "Placeholder label. Final transparency wording comes in M5.",
        "signals": {"llm": llm},
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
