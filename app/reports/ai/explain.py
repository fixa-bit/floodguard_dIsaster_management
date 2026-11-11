"""Step 2: a short, cited explanation of one flagged signal, from retrieved documents (RAG).

The flag's measured value and category come from code and are given to the model as fixed
facts. Retrieved passages go in as search_result blocks with citations, so every sentence in
the answer can point to the passage it used. No passages, no call.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.reports.ai.client import Usage, create, refusal_text
from app.reports.ai.knowledge import KIND_NAMES, Hit, KnowledgeBase

SYSTEM = (
    "You help flood-operations supervisors in Pakistan (NDMA, PDMA, FFD and irrigation staff) understand why "
    "FloodGuard flagged a value in its report.\n"
    "FloodGuard's code has already measured the value and assigned its risk category using fixed rules. Treat both as "
    "given facts: explain them, but never re-grade, dispute or recalculate them, and do not suggest a different "
    "category or status.\n"
    "Use only the search results provided. Every factual statement must be supported by a search result. If the search "
    "results do not explain this signal, say so plainly in one sentence instead of guessing.\n"
    "Write 2 to 4 short sentences in plain English. No headings, no bullet points, and no instructions beyond what the "
    "cited documents say."
)


def facts_text(flag: dict, report_meta: dict) -> str:
    m, c = flag["measured"], flag["category"]
    lines = [
        "Flagged signal, computed by FloodGuard's code (fixed facts, do not change):",
        f"- What: {flag['title']}",
        f"- Measured: {m['label']}: {m['value']}" + (f" ({m['detail']})" if m.get("detail") else "") + (f", at {m['time']} PKT" if m.get("time") else ""),
        f"- Risk category: {c['label']} (rule: {c['rule']})",
        f"- Effect on status: {c['status_effect']}",
        f"- Place: {flag.get('location') or '—'}" + (f", {flag['river']} river" if flag.get("river") else ""),
        f"- Report: {report_meta.get('report_no')} ({report_meta.get('period') or report_meta.get('generated') or ''})",
    ]
    if flag.get("simulated"):
        lines.append("- Note: this signal comes from a SIMULATED test reading, not real data. Say so in your answer.")
    return "\n".join(lines)


def retrieve(kb: KnowledgeBase, flag: dict, exclude_doc_ids: set[str]) -> list[Hit]:
    hits = kb.search(flag["query_terms"], anchors=flag.get("anchor_terms"), exclude_doc_ids=exclude_doc_ids)
    if len(hits) < 3 and flag.get("river"):  # widen to the river when the place itself is rarely named
        seen = {h.chunk_id for h in hits}
        more = kb.search(flag["query_terms"], anchors=[flag["river"]], exclude_doc_ids=exclude_doc_ids)
        hits += [h for h in more if h.chunk_id not in seen][: 6 - len(hits)]
    return hits


def search_result_block(hit: Hit, citations: bool = True) -> dict:
    title = f"{hit.title} [{KIND_NAMES.get(hit.kind, hit.kind)}" + (f", {hit.published}" if hit.published else "") + "]"
    return {"type": "search_result", "source": hit.source, "title": title,
            "content": [{"type": "text", "text": hit.text}], "citations": {"enabled": citations}}


def explain_flag(client, kb: KnowledgeBase, flag: dict, report_meta: dict, exclude_doc_ids: set[str]) -> dict:
    """Returns {status, segments[{text, cites[]}], sources[...], retrieved[...], usage}."""
    settings = get_settings()
    hits = retrieve(kb, flag, exclude_doc_ids)
    retrieved = [h.as_dict() for h in hits]
    if not hits:
        return {"status": "no_documents", "segments": [], "sources": [], "retrieved": [],
                "note": "No matching bulletins, procedures or past reports were found for this signal."}
    usage = Usage()
    content = [{"type": "text", "text": facts_text(flag, report_meta)}]
    content += [search_result_block(h) for h in hits]
    content.append({"type": "text", "text": "Using only these search results, explain what this flagged signal means and what "
                                            "the documents say about it or about similar situations at this place."})
    message = create(client, usage, max_tokens=4000, system=SYSTEM, output_config={"effort": settings.ai_explain_effort},
                     messages=[{"role": "user", "content": content}])
    declined = refusal_text(message)
    if declined:
        return {"status": "declined", "segments": [], "sources": [], "retrieved": retrieved, "note": declined, "usage": usage.as_dict()}
    segments, sources, numbers = [], [], {}
    for block in message.content:
        if getattr(block, "type", None) != "text" or not block.text:
            continue
        cites = []
        for c in getattr(block, "citations", None) or []:
            if getattr(c, "type", None) != "search_result_location":
                continue
            index = c.search_result_index
            hit = hits[index] if 0 <= index < len(hits) else None
            key = (index, c.start_block_index)
            if key not in numbers:
                numbers[key] = len(numbers) + 1
                sources.append({"n": numbers[key], "source": c.source, "title": hit.title if hit else c.title,
                                "kind": hit.kind if hit else None, "kind_name": KIND_NAMES.get(hit.kind, "") if hit else "",
                                "published": hit.published if hit else None, "url": hit.url if hit else None,
                                "page": hit.page if hit else None, "cited_text": (c.cited_text or "")[:600]})
            if numbers[key] not in cites:
                cites.append(numbers[key])
        segments.append({"text": block.text, "cites": cites})
    if not segments:
        return {"status": "empty", "segments": [], "sources": [], "retrieved": retrieved, "note": "The model returned no text.",
                "usage": usage.as_dict()}
    return {"status": "complete", "segments": segments, "sources": sources, "retrieved": retrieved,
            "uncited": sum(1 for s in segments if not s["cites"] and len(s["text"].strip()) > 40), "usage": usage.as_dict()}
