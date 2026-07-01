"""Structured audit log for Provenance Guard.

Every decision the service makes is appended here as a JSON record. The store
is a single JSON file holding a list of entries, which is easy to inspect and
to show through GET /log later. SQLite would also work; JSON keeps it simple
and human-readable for this project.

Milestone 3 writes the first fields. Milestone 4 extends each entry (second
signal, combined score), and Milestone 5 adds appeals and status changes, plus
reads for GET /log.
"""

import json
import os
import threading

# The log file lives next to this module, at the project root.
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_log.json")

# Guard reads and writes so two requests can't corrupt the JSON.
_lock = threading.Lock()


def _read_all():
    """Return every entry as a list. A missing or empty file means no entries."""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    return json.loads(content)


def _write_all(entries):
    """Overwrite the log file with the full list of entries."""
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def append_entry(entry):
    """Append one decision record to the log and return it."""
    with _lock:
        entries = _read_all()
        entries.append(entry)
        _write_all(entries)
    return entry


def read_all():
    """Return all entries in the order they were written (oldest first)."""
    with _lock:
        return _read_all()


def add_appeal(content_id, appeal):
    """Attach an appeal to an existing decision.

    Finds the decision by content_id, appends the appeal to its "appeals" list
    (creating the list if this is the first appeal), and flips its status to
    "under_review". The whole read-modify-write runs under the lock so a
    concurrent submit or appeal can't clobber it.

    Returns the updated entry, or None if no decision has that content_id (the
    caller turns None into a 404).
    """
    with _lock:
        entries = _read_all()
        for entry in entries:
            if entry.get("content_id") == content_id:
                entry.setdefault("appeals", []).append(appeal)
                entry["status"] = "under_review"
                _write_all(entries)
                return entry
        return None


def is_healthy():
    """True if the log store is reachable: readable now and writable going on.

    Used by GET /health. Reads the file (a missing or empty file is fine, it
    means no entries yet) and confirms the directory it lives in is writable, so
    the next append will succeed. Any parse or access error means unhealthy.
    """
    try:
        with _lock:
            _read_all()
    except Exception:
        return False
    return os.access(os.path.dirname(LOG_PATH), os.W_OK)
