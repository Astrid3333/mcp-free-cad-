# Fitting-history handlers for FreeCAD MCP
#
# Extends the existing save_fixture/compare_to_fixture pattern (see
# fixture_ops.py) into a purpose-built log for *clinical fitting sessions*:
# every time a socket is adjusted for a real user, save a timestamped
# fixture plus structured notes (pressure complaints, don/doff time,
# range-of-motion), so the adjustment history is versioned and queryable
# instead of living in someone's memory or a paper notebook.
#
# Design decisions:
#   - Deliberately thin: this module reuses fixture_ops's save_fixture for
#     the actual geometry snapshot and only adds a session-log layer on
#     top (fitting_log.json per fixture family), rather than duplicating
#     STL/topology export logic.
#   - One "fixture family" = one patient's socket iteration history, keyed
#     by a patient_id the caller provides. No PII is required or stored —
#     callers should pass a non-identifying code (e.g. initials + number),
#     consistent with community fabrication practice for privacy.
#   - Sessions are append-only; nothing is overwritten, so the full
#     adjustment trail is auditable.

import json
import os
import time
from typing import Any, Dict, List

from .base import BaseHandler
from .fixture_ops import _fixtures_root, _safe_name  # reuse path/name helpers


def _fitting_log_path(patient_id: str) -> str:
    return os.path.join(_fixtures_root(), "fitting_logs", f"{patient_id}.json")


def _load_log(patient_id: str) -> List[Dict[str, Any]]:
    path = _fitting_log_path(patient_id)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(patient_id: str, entries: List[Dict[str, Any]]) -> None:
    path = _fitting_log_path(patient_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


class FittingHistoryOpsHandler(BaseHandler):
    """Session-log layer over fixture_ops for tracking socket-fitting
    iterations per patient/user over time."""

    _ALLOWED_OPERATIONS = frozenset({
        "log_fitting_session", "get_fitting_history", "compare_to_last_fitting",
    })

    # ------------------------------------------------------------------
    def log_fitting_session(self, args: Dict[str, Any]) -> str:
        """Save a geometry fixture for the current socket AND append a
        structured note about this fitting session.

        Args:
          shape:          name of the socket object to snapshot
          patient_id:     non-identifying code for the patient/user
          session_notes:  free-text notes (complaints, observations)
          pressure_complaints: list of strings, e.g. ["tight at distal end"]
          donning_time_sec: optional, how long it took to put on
          fit_rating:     optional int 1-5 subjective fit rating

        Returns JSON with the fixture name used and the updated session count.
        """
        try:
            object_name = args.get("shape", "")
            patient_id = args.get("patient_id", "")
            if not object_name or not patient_id:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing shape or patient_id"})
            if not _safe_name(patient_id):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Invalid patient_id {patient_id!r} — "
                                               f"alphanumerics/underscores/hyphens only"})

            existing = _load_log(patient_id)
            session_num = len(existing) + 1
            fixture_name = f"{patient_id}_session{session_num:03d}"

            # Delegate the actual geometry snapshot to fixture_ops's logic
            # by importing the sibling handler class directly.
            from .fixture_ops import FixtureOpsHandler
            fixture_handler = FixtureOpsHandler(self.freecad_conn) \
                if hasattr(self, "freecad_conn") else FixtureOpsHandler.__new__(FixtureOpsHandler)
            # Reuse BaseHandler plumbing from self so document/object lookup
            # matches whatever connection context this handler was built with.
            fixture_handler.__dict__.update(self.__dict__)

            fixture_result = json.loads(fixture_handler.save_fixture({
                "shape": object_name,
                "fixture_name": fixture_name,
                "description": args.get("session_notes", ""),
            }))

            entry = {
                "session_number": session_num,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "fixture_name": fixture_name,
                "shape": object_name,
                "session_notes": args.get("session_notes", ""),
                "pressure_complaints": args.get("pressure_complaints", []),
                "donning_time_sec": args.get("donning_time_sec"),
                "fit_rating": args.get("fit_rating"),
                "fixture_ok": fixture_result.get("ok", False),
            }
            existing.append(entry)
            _save_log(patient_id, existing)

            return json.dumps({
                "ok": fixture_result.get("ok", False),
                "details": {"entry": entry, "total_sessions": len(existing)},
                "message": (
                    f"Logged fitting session #{session_num} for patient "
                    f"'{patient_id}' (fixture '{fixture_name}'). "
                    f"{len(existing)} session(s) on record."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in log_fitting_session: {e}"})

    # ------------------------------------------------------------------
    def get_fitting_history(self, args: Dict[str, Any]) -> str:
        """Return the full logged fitting-session history for a patient.

        Args:
          patient_id: non-identifying code

        Returns JSON with the list of session entries, newest last.
        """
        try:
            patient_id = args.get("patient_id", "")
            if not patient_id:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing patient_id"})

            entries = _load_log(patient_id)
            return json.dumps({
                "ok": True,
                "details": {"sessions": entries, "count": len(entries)},
                "message": f"{len(entries)} fitting session(s) on record for "
                           f"'{patient_id}'." if entries else
                           f"No fitting sessions logged yet for '{patient_id}'.",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in get_fitting_history: {e}"})

    # ------------------------------------------------------------------
    def compare_to_last_fitting(self, args: Dict[str, Any]) -> str:
        """Compare the current socket shape against the most recently
        logged fitting-session fixture for this patient (delegates the
        geometric comparison to fixture_ops.compare_to_fixture).

        Args:
          shape:      current socket object name
          patient_id: non-identifying code

        Returns JSON with the comparison result plus the prior session's
        notes/complaints for context.
        """
        try:
            object_name = args.get("shape", "")
            patient_id = args.get("patient_id", "")
            if not object_name or not patient_id:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing shape or patient_id"})

            entries = _load_log(patient_id)
            if not entries:
                return json.dumps({"ok": False, "details": {},
                                    "message": f"No prior fitting sessions for "
                                               f"'{patient_id}' to compare against."})

            last = entries[-1]

            from .fixture_ops import FixtureOpsHandler
            fixture_handler = FixtureOpsHandler.__new__(FixtureOpsHandler)
            fixture_handler.__dict__.update(self.__dict__)

            cmp_result = json.loads(fixture_handler.compare_to_fixture({
                "shape": object_name,
                "fixture_name": last["fixture_name"],
            }))

            return json.dumps({
                "ok": cmp_result.get("ok", False),
                "details": {
                    "comparison": cmp_result.get("details", {}),
                    "prior_session": last,
                },
                "message": (
                    f"{cmp_result.get('message', '')} "
                    f"(comparing against session #{last['session_number']}, "
                    f"{last['timestamp']}, prior notes: "
                    f"{last.get('session_notes') or 'none'})"
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in compare_to_last_fitting: {e}"})
