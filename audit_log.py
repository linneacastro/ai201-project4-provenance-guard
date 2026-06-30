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
