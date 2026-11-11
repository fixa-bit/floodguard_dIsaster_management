"""Phase 2 of report generation: AI analysis of the flags that code raised.

Runs after the deterministic report (phase 1) is written. It reads report.json, explains the
top flags with cited documents (explain.py), runs the bounded agent on the top flags
(agent.py), checks that no code-computed value changed (SHA-256 of everything except the AI
block), writes report.json["ai_analysis"] and re-renders the page. Any failure leaves the
phase-1 report intact with "AI analysis not run: <reason>".
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.reports.ai.agent import analyse_flag
from app.reports.ai.client import PROMPT_VERSION, AIUnavailable, make_client
from app.reports.ai.explain import explain_flag
from app.reports.ai.knowledge import KnowledgeBase, fetch_current_bulletin
from app.reports.render import render_folder, write_atomic

logger = logging.getLogger(__name__)
CODE_OWNED_EXCLUDE = ("ai_analysis", "review")


def facts_digest(data: dict) -> str:
    """Checksum of every code-owned value in a report (all keys except the AI block and reviews)."""
    facts = {k: v for k, v in data.items() if k not in CODE_OWNED_EXCLUDE}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def review_mode_for(trigger: str, requested: str | None) -> str:
    """Automatic reports (schedule, watcher) need no human review by default; manual ones choose portal or label."""
    settings = get_settings()
    if trigger in ("scheduled", "watcher"):
        return settings.ai_review_automatic
    return requested if requested in ("portal", "label") else settings.ai_review_manual_default


def placeholder(enabled: bool, trigger: str, review_mode: str, reason: str | None = None) -> dict:
    """The AI block written with the phase-1 report, before any AI runs."""
    return {"status": "pending" if enabled else "off", "trigger": trigger, "review_mode": review_mode,
            "reason": reason or (None if enabled else "AI analysis was switched off for this report."), "flags": {}}


def run_ai_analysis(folder: Path, *, trigger: str, review_mode: str, include_simulated: bool = False, progress=None) -> dict:
    settings = get_settings()
    say = progress or (lambda _msg: None)
    report_path = folder / "report.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    before = facts_digest(data)
    started = time.monotonic()
    ai = {"status": "running", "model": settings.ai_model, "prompt_version": PROMPT_VERSION, "trigger": trigger,
          "review_mode": review_mode, "started_at": datetime.now(timezone.utc).isoformat(), "flags": {}, "reason": None,
          "limits": {"explanations": settings.ai_max_explanations, "agent_runs": settings.ai_max_agent_runs,
                     "agent_turns": settings.ai_agent_max_turns, "agent_tool_calls": settings.ai_agent_max_tool_calls,
                     "web_searches_per_run": settings.ai_web_search_max_uses if settings.ai_web_search else 0}}
    transcript: dict[str, list] = {}
    flags = data.get("flags") or []
    candidates = [f for f in flags if include_simulated or not f.get("simulated")]
    try:
        if not flags:
            ai.update(status="no_flags", reason="No rule flagged a value in this report, so no AI analysis was run.")
        elif not candidates:
            ai.update(status="skipped", reason="Only simulated signals were flagged, and AI analysis of simulated signals is off for this run.")
        else:
            client = make_client()
            say("AI analysis: refreshing the document index")
            kb = KnowledgeBase()
            fetch_current_bulletin(kb.root)
            ai["knowledge"] = kb.refresh()
            reports_root = kb.reports_root.resolve()
            current = folder.resolve()
            exclude = {f"report/{current.relative_to(reports_root).as_posix()}"} if current.is_relative_to(reports_root) else set()
            meta = {**data.get("meta", {})}
            failures, stop_reason = 0, None
            for flag in candidates[: settings.ai_max_explanations]:
                if time.monotonic() - started > settings.ai_timeout_seconds:
                    stop_reason = "Time limit reached before all flags were explained."
                    break
                say(f"AI analysis: explaining {flag['id']} ({flag['title']})")
                try:
                    ai["flags"].setdefault(flag["id"], {})["explanation"] = explain_flag(client, kb, flag, meta, exclude)
                except AIUnavailable as exc:
                    stop_reason = str(exc)
                    break
                except Exception as exc:  # one flag failing must not lose the others
                    logger.exception("Explanation failed for %s", flag["id"])
                    ai["flags"].setdefault(flag["id"], {})["explanation"] = {"status": "failed", "note": f"{type(exc).__name__}: {exc}"}
                    failures += 1
            if stop_reason is None:
                for flag in [f for f in candidates if f.get("agent_eligible")][: settings.ai_max_agent_runs]:
                    if time.monotonic() - started > settings.ai_timeout_seconds:
                        stop_reason = "Time limit reached before the deeper analysis finished."
                        break
                    say(f"AI analysis: deeper look at {flag['id']} ({flag['title']})")
                    try:
                        result, transcript[flag["id"]] = analyse_flag(client, flag, data, kb, settings.report_api_base, exclude)
                        ai["flags"].setdefault(flag["id"], {})["agent"] = result
                        failures += result["status"] != "complete"
                    except AIUnavailable as exc:
                        stop_reason = str(exc)
                        break
                    except Exception as exc:
                        logger.exception("Agent failed for %s", flag["id"])
                        ai["flags"].setdefault(flag["id"], {})["agent"] = {"status": "failed", "note": f"{type(exc).__name__}: {exc}"}
                        failures += 1
            if stop_reason and not ai["flags"]:
                ai.update(status="unavailable", reason=stop_reason)
            elif stop_reason or failures:
                ai.update(status="partial", reason=stop_reason)
            else:
                ai["status"] = "complete"
            not_covered = len(candidates) - len(ai["flags"])
            if not_covered > 0 and ai["status"] in ("complete", "partial"):
                ai["note"] = f"{not_covered} lower-priority flag(s) were not analysed (limit {settings.ai_max_explanations})."
    except AIUnavailable as exc:
        ai.update(status="unavailable", reason=str(exc))
    except Exception as exc:
        logger.exception("AI analysis failed for %s", folder)
        ai.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    after = facts_digest(data)
    ai["integrity"] = {"facts_sha256": before, "unchanged": before == after,
                       "note": "Code-computed values were not changed by the AI step (checksum verified)." if before == after else
                               "Code-computed values changed during the AI step; the AI analysis was discarded."}
    if before != after:  # never expected; the AI code only reads report data
        logger.error("AI step changed code-owned report data in %s; discarding AI output", folder)
        data = json.loads(report_path.read_text(encoding="utf-8"))
        ai = {**placeholder(True, trigger, review_mode), "status": "failed", "integrity": ai["integrity"],
              "reason": ai["integrity"]["note"]}
    ai["finished_at"] = datetime.now(timezone.utc).isoformat()
    ai["seconds"] = round(time.monotonic() - started, 1)
    data["ai_analysis"] = ai
    write_atomic(report_path, json.dumps(data, ensure_ascii=False, indent=1, default=str))
    if transcript:
        write_atomic(folder / "ai_transcript.json", json.dumps(transcript, ensure_ascii=False, indent=1, default=str))
    render_folder(folder)
    say(f"AI analysis: {ai['status']}")
    return ai
