"""Step 3: a bounded, read-only agent that looks deeper at one flagged signal.

Manual tool loop (not the SDK tool runner) because tools return search_result blocks and the
run needs exact caps: at most ai_agent_max_turns turns, ai_agent_max_tool_calls tool calls and
ai_agent_seconds of wall time. The agent ends by calling submit_findings (strict schema, no
status or category fields). Code then keeps only statements whose references were really issued
in this run: T-numbers from data tools, document sources, or web URLs returned by web search.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import anthropic

from app.core.config import get_settings
from app.reports.ai.client import AIUnavailable, Usage, create, refusal_text
from app.reports.ai.explain import facts_text
from app.reports.ai.tools import SUBMIT_TOOL, TOOL_DEFS, AgentTools

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are FloodGuard's analysis assistant for flood-operations supervisors in Pakistan.\n"
    "A rule in FloodGuard's code flagged the value described by the user. FloodGuard's code owns the measured value, the "
    "risk category and the national status. You cannot change them and must not propose new ones.\n"
    "Your job: find out why the flagged value may have happened and what it could mean. Use the read-only tools to compare it "
    "with recent readings, upstream stations and dam or barrage releases, forecasts, rainfall, incidents and citizen reports, "
    "the satellite check, and documents (FFD bulletins, Federal Flood Commission reports, NDMA/PDMA plans, flood "
    "classification limits, past FloodGuard reports). Use web search only for recent official advisories or news about this "
    "river, structure or district.\n"
    "Every data tool result has a reference such as T3. Documents and web pages are referenced by their source string or URL. "
    "Every evidence item and explanation you submit must list the references it relies on. Never cite anything you did not "
    "receive from a tool in this conversation.\n"
    "Be honest about uncertainty: say when data is missing, stale, simulated or contradictory. Numbers must come from tool "
    "results; do not estimate values you did not see.\n"
    "Work efficiently. When you have enough evidence, call submit_findings once. Keep each finding to one or two sentences."
)


def _block_dict(block) -> dict:
    if hasattr(block, "model_dump"):
        data = block.model_dump(exclude_none=True)
    elif isinstance(block, dict):
        data = dict(block)
    else:
        data = {k: v for k, v in vars(block).items() if not k.startswith("_")}
    if data.get("type") == "web_search_tool_result" and isinstance(data.get("content"), list):
        data["content"] = [{k: v for k, v in r.items() if k != "encrypted_content"} for r in data["content"]]
    return data


def _web_results(content) -> list[dict]:
    found = []
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        if isinstance(results, list):
            for r in results:
                if getattr(r, "url", None):
                    found.append({"ref": r.url, "kind": "web", "label": getattr(r, "title", None) or r.url, "url": r.url,
                                  "page_age": getattr(r, "page_age", None), "domain": urlparse(r.url).netloc})
    return found


def _normalise(ref: str) -> str:
    return (ref or "").strip().strip("[]()").rstrip("/")


def validate(findings: dict, known: dict[str, dict]) -> tuple[dict, int]:
    """Keep statements with at least one reference issued in this run; drop unknown references."""
    lookup = {_normalise(k): k for k in known}
    dropped = 0

    def clean(refs):
        out = []
        for r in refs or []:
            key = lookup.get(_normalise(r))
            if key and key not in out:
                out.append(key)
        return out

    evidence, explanations = [], []
    for e in findings.get("evidence") or []:
        refs = clean(e.get("refs"))
        if refs and e.get("finding"):
            evidence.append({"finding": e["finding"], "relation": e.get("relation", "context"), "refs": refs})
        else:
            dropped += 1
    for x in findings.get("possible_explanations") or []:
        refs = clean(x.get("refs"))
        if refs and x.get("explanation"):
            explanations.append({"explanation": x["explanation"], "likelihood": x.get("likelihood", "possible"), "refs": refs})
        else:
            dropped += 1
    uncertainty = findings.get("uncertainty") or {}
    result = {"summary": (findings.get("summary") or "").strip(), "evidence": evidence[:8], "possible_explanations": explanations[:4],
              "uncertainty": {"level": uncertainty.get("level", "high"), "reasons": list(uncertainty.get("reasons") or [])[:5]},
              "reviewer_checks": list(findings.get("reviewer_checks") or [])[:5]}
    return result, dropped


def analyse_flag(client, flag: dict, report: dict, kb, api_base: str, exclude_doc_ids: set[str]) -> tuple[dict, list]:
    """Run the bounded agent for one flag. Returns (result, transcript)."""
    settings = get_settings()
    usage = Usage()
    tools = AgentTools(report, kb, api_base, exclude_doc_ids, max_calls=settings.ai_agent_max_tool_calls)
    web_tool = {"type": "web_search_20260209", "name": "web_search", "max_uses": settings.ai_web_search_max_uses,
                "allowed_domains": [d.strip() for d in settings.ai_web_search_domains.split(",") if d.strip()]}
    web_state = "on" if settings.ai_web_search else "off"
    web_refs: dict[str, dict] = {}
    station_hint = f" Station id: {flag['station_id']}." if flag.get("station_id") else ""
    messages = [{"role": "user", "content": [{"type": "text", "text": facts_text(flag, report.get("meta", {})) + station_hint
                                                                     + "\n\nInvestigate this flagged signal, then call submit_findings."}]}]
    transcript = []
    started = time.monotonic()
    status, note, turns, asked_to_submit = "incomplete", None, 0, False
    web_used, web_told = 0, False
    max_turns = settings.ai_agent_max_turns
    while turns < max_turns:
        turns += 1
        out_of_time = time.monotonic() - started > settings.ai_agent_seconds
        if (out_of_time or tools.calls >= tools.max_calls or turns == max_turns) and not asked_to_submit and tools.findings is None:
            messages.append({"role": "user", "content": [{"type": "text", "text": "Time or tool budget is used up. Call submit_findings now "
                                                                                  "with the evidence you already have."}]})
            asked_to_submit = True
        web_left = settings.ai_web_search_max_uses - web_used
        if web_state == "on" and web_left <= 0 and not web_told:
            messages.append({"role": "user", "content": [{"type": "text", "text": "The web search budget for this analysis is used up. "
                                                                                  "Do not search the web again."}]})
            web_told = True
        request_tools = TOOL_DEFS + [SUBMIT_TOOL] + ([{**web_tool, "max_uses": max(web_left, 1)}] if web_state == "on" else [])
        params = dict(max_tokens=16000, system=SYSTEM, tools=request_tools, messages=messages,
                      output_config={"effort": settings.ai_agent_effort}, cache_control={"type": "ephemeral"})
        try:
            message = create(client, usage, **params)
        except anthropic.BadRequestError as exc:
            if web_state == "on" and "web_search" in str(exc).lower():
                web_state = "unavailable"  # e.g. web search disabled for the organization
                logger.warning("Web search unavailable, continuing without it: %s", exc)
                turns -= 1
                continue
            raise AIUnavailable(f"The Anthropic API rejected the request: {getattr(exc, 'message', exc)}") from exc
        transcript.append({"turn": turns, "stop_reason": message.stop_reason, "content": [_block_dict(b) for b in message.content]})
        declined = refusal_text(message)
        if declined:
            status, note = "declined", declined
            break
        for r in _web_results(message.content):
            web_refs.setdefault(r["ref"], r)
        web_used += sum(1 for b in message.content if getattr(b, "type", None) == "server_tool_use" and getattr(b, "name", "") == "web_search")
        messages.append({"role": "assistant", "content": message.content})
        if message.stop_reason == "pause_turn":
            continue  # a server tool paused; sending the history again resumes it
        if message.stop_reason == "max_tokens":
            note = "The agent's answer was cut off at the token limit."
            break
        tool_uses = [b for b in message.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            if tools.findings is None and not asked_to_submit and turns < max_turns:
                messages.append({"role": "user", "content": [{"type": "text", "text": "Please call submit_findings with your findings."}]})
                asked_to_submit = True
                continue
            break
        results = []
        for use in tool_uses:
            content, is_error = tools.execute(use.name, dict(use.input or {}))
            block = {"type": "tool_result", "tool_use_id": use.id, "content": content}
            if is_error:
                block["is_error"] = True
            results.append(block)
        transcript.append({"turn": turns, "tool_results": [{"tool": u.name, "input": dict(u.input or {}),
                                                             "summary": tools.log[i - len(tool_uses)]["result"] if tools.log else ""}
                                                            for i, u in enumerate(tool_uses)]})
        if tools.findings is not None:
            status = "complete"
            break
        messages.append({"role": "user", "content": results})
    if tools.findings is None and status != "declined":
        status, note = "incomplete", note or "The agent did not submit findings within its limits."
    known = {**tools.refs, **tools.doc_refs, **web_refs}
    result = {"status": status, "note": note, "turns": turns, "tool_calls": tools.calls, "web_search": web_state, "web_searches": web_used,
              "seconds": round(time.monotonic() - started, 1), "usage": usage.as_dict(), "tool_log": tools.log}
    if tools.findings is not None:
        cleaned, dropped = validate(tools.findings, known)
        used = {r for item in cleaned["evidence"] + cleaned["possible_explanations"] for r in item["refs"]}
        result.update(cleaned, dropped_statements=dropped, references={k: v for k, v in known.items() if k in used})
    return result, transcript
