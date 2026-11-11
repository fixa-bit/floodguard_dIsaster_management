"""Human review of AI notes. Decisions live in review.json beside report.json; report.json is never changed."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.reports.render import render_folder, write_atomic

DECISIONS = ("accepted", "rejected")


def load_review(folder: Path) -> dict:
    path = folder / "review.json"
    if not path.exists():
        return {"flags": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def ai_summary(data: dict, review: dict) -> dict | None:
    """Counts for the portal list: notes, review mode and how many still need review."""
    ai = data.get("ai_analysis")
    if not ai:
        return None
    notes = [fid for fid, entry in (ai.get("flags") or {}).items()
             if (entry.get("explanation") or {}).get("status") == "complete" or (entry.get("agent") or {}).get("status") in ("complete", "incomplete")]
    reviewed = [fid for fid in notes if fid in (review.get("flags") or {})]
    mode = ai.get("review_mode", "label")
    return {"status": ai.get("status"), "reason": ai.get("reason"), "review_mode": mode, "trigger": ai.get("trigger"),
            "notes": len(notes), "reviewed": len(reviewed), "to_review": len(notes) - len(reviewed) if mode == "portal" else 0}


def save_decision(folder: Path, flag_id: str, decision: str, note: str, reviewer: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError("Decision must be accepted or rejected.")
    reviewer = " ".join((reviewer or "").split())[:80]
    if not reviewer:
        raise ValueError("Enter the reviewer's name.")
    data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if flag_id not in ((data.get("ai_analysis") or {}).get("flags") or {}):
        raise ValueError(f"No AI note for flag {flag_id} in this report.")
    review = load_review(folder)
    review.setdefault("flags", {})[flag_id] = {"decision": decision, "note": (note or "").strip()[:1000], "reviewer": reviewer,
                                               "at": datetime.now(timezone.utc).isoformat()}
    review["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_atomic(folder / "review.json", json.dumps(review, ensure_ascii=False, indent=1))
    render_folder(folder)
    return review


def clear_decision(folder: Path, flag_id: str) -> dict:
    review = load_review(folder)
    review.get("flags", {}).pop(flag_id, None)
    review["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_atomic(folder / "review.json", json.dumps(review, ensure_ascii=False, indent=1))
    render_folder(folder)
    return review
