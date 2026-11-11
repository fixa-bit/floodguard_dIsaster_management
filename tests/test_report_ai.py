"""AI analysis of flagged report signals: flags, document search, tools, agent loop, integrity, review.

No network and no API credit: Claude is replaced by a fake client that returns scripted responses.
"""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.reports.ai import agent as agent_mod
from app.reports.ai import review as review_mod
from app.reports.ai.agent import analyse_flag, validate
from app.reports.ai.explain import explain_flag
from app.reports.ai.knowledge import METHOD_NOTES, KnowledgeBase, report_text
from app.reports.collector import ROOT
from app.reports.ai.runner import facts_digest, review_mode_for
from app.reports.ai.tools import AgentTools
from app.reports.flags import build_daily_flags, build_event_flags


# ---------------------------------------------------------------- fixtures
def station(sid, name, river, discharge, change, category="Below low", **extra):
    return {"id": sid, "name": name, "river": river, "available": True, "discharge": discharge, "change_24h": change,
            "category": category, "stale": False, "observed_at": "11 Nov 06:00", "inflow": None, "outflow": None, **extra}


def daily_report():
    return {
        "meta": {"report_no": "DFSR-TEST-1", "period": "test period"},
        "stations": [station("TRIMMU", "Trimmu", "Chenab", 9500, 400, "High flood"),
                     station("KALABAGH", "Kalabagh", "Indus", 3992.5, 2183.9),
                     station("ISLAM", "Islam", "Sutlej", 51, 21.3)],
        "upstream": {"stations": [
            {"id": "u1", "name": "Chenab Marala", "river": "Chenab", "agreement_pct": 56, "gap_cumecs": 306, "agree": False,
             "low_flood_threshold": None, "providers": [{"provider": "GloFAS", "peak": 243, "status": "available"},
                                                        {"provider": "GEOGloWS", "peak": 548, "status": "available"}]},
            {"id": "u2", "name": "Ravi Jassar", "river": "Ravi", "agreement_pct": 5, "gap_cumecs": 10, "agree": True,
             "low_flood_threshold": 1000, "low_flood_threshold_kind": "official",
             "providers": [{"provider": "GloFAS", "peak": 1200, "status": "available"}, {"provider": "GEOGloWS", "peak": 900, "status": "available"}]}]},
        "satellite": {"checks": [
            {"location": "Taunsa station", "station_id": "TAUNSA", "gauge_category": "Below low", "result": "potential_flooding_detected",
             "potential_flood_area_km2": 11.5, "during_date": "2026-11-07", "triggered_by_simulation": False},
            {"location": "Trimmu station", "station_id": "TRIMMU", "gauge_category": "High flood", "result": "potential_flooding_detected",
             "potential_flood_area_km2": 9.0, "during_date": "2026-11-10", "triggered_by_simulation": False,
             "image_data_url": "data:image/png;base64,AAAA"}]},
        "districts": {"top_risk": [{"district": "Astore", "risk": 32, "factors": []}, {"district": "Swat", "risk": 64, "factors": ["rain"]}]},
        "summary": {"status": "Emergency", "headline": "Trimmu in High flood.", "concerns": [
            {"text": "Real concern at Trimmu.", "sources": ["obs"]}, {"text": "Simulated test alert.", "sources": ["sim"]}]},
    }


# ---------------------------------------------------------------- flags
def test_daily_flags_follow_the_report_rules():
    flags = build_daily_flags(daily_report())
    kinds = [(f["kind"], f["location"]) for f in flags]
    assert ("observed_flood", "Trimmu") in kinds
    assert ("sharp_rise", "Kalabagh") in kinds
    assert ("sharp_rise", "Islam") not in kinds                  # +21 cumecs: below the 50 cumecs rule
    assert ("forecast_disagreement", "Chenab Marala") in kinds
    assert ("forecast_threshold", "Ravi Jassar") in kinds        # 1200 >= 1000 and 900 >= 750
    assert ("satellite_water", "Trimmu station") in kinds
    assert ("satellite_water", "Taunsa station") not in kinds   # barrage rule: gauge Below low
    assert ("district_high", "Swat") in kinds and ("district_high", "Astore") not in kinds
    assert flags[0]["kind"] == "observed_flood" and flags[0]["id"] == "F1"
    assert flags[0]["category"]["status_effect"].startswith("Raises the national status to Emergency")
    for f in flags:  # flags hold code facts only
        assert set(f) >= {"measured", "category", "anchor_terms", "query_terms"} and "explanation" not in f


def test_event_flags_mark_simulated_signals():
    data = {"stations": [station("TRIMMU", "Trimmu", "Chenab", 300, 0)], "event": {"signals": [
        {"kind": "observed", "river": "Chenab", "station_id": "TRIMMU", "station_name": "Trimmu", "label": "High flood",
         "level": 4, "value_cumecs": 9500, "at": "2026-11-11T01:00:00+00:00", "sources": ["sim"], "simulated": True}]}}
    flags = build_event_flags(data)
    assert len(flags) == 1 and flags[0]["simulated"] and flags[0]["measured"]["sources"] == ["sim"]
    assert flags[0]["measured"]["value"].startswith("9,500")


# ---------------------------------------------------------------- knowledge base
def test_knowledge_search_and_exclusions(tmp_path):
    kroot, rroot = tmp_path / "knowledge", tmp_path / "reports"
    (kroot / "procedures").mkdir(parents=True)
    (kroot / "procedures" / "plan.md").write_text(
        "# Chenab plan\n\nAt Trimmu Headworks a High flood means embankments are under pressure and breaching sections may be "
        "operated to protect the structure.\n\nOther rivers are covered elsewhere in this plan for completeness of the text.", encoding="utf-8")
    real = daily_report() | {"flags": build_daily_flags(daily_report()), "ai_analysis": {"flags": {"F1": {"explanation": {"segments": [{"text": "AI SECRET TEXT"}]}}}}}
    (rroot / "daily" / "2026-11-10_063000").mkdir(parents=True)
    (rroot / "daily" / "2026-11-10_063000" / "report.json").write_text(json.dumps(real), encoding="utf-8")
    test_event = {"meta": {"report_no": "FER-TEST-X", "is_test": True}, "event": {}, "summary": {"headline": "TEST EVENT Trimmu"}}
    (rroot / "events" / "test" / "FER-TEST-X" / "v1").mkdir(parents=True)
    (rroot / "events" / "test" / "FER-TEST-X" / "v1" / "report.json").write_text(json.dumps(test_event), encoding="utf-8")
    kb = KnowledgeBase(root=kroot, reports_root=rroot)
    stats = kb.refresh()
    method_notes = [rel for rel in METHOD_NOTES if (ROOT / rel).is_file()]
    assert stats["indexed"] == 2 + len(method_notes)  # plan + one past report (test event skipped) + repo method notes
    hits = kb.search(["Trimmu", "flood"], anchors=["Trimmu"])
    texts = " ".join(h.text for h in hits)
    assert "embankments are under pressure" in texts
    assert "AI SECRET TEXT" not in texts and "TEST EVENT" not in texts
    assert all("trimmu" in (h.title + h.text).lower() for h in hits)
    assert kb.refresh()["unchanged"] == stats["documents"]      # nothing re-indexed when nothing changed


def test_report_text_skips_simulated_and_ai_content():
    text = report_text(daily_report() | {"ai_analysis": {"flags": {"F1": {"explanation": {"note": "AI WORDS"}}}}})
    assert "Real concern at Trimmu" in text and "Simulated test alert" not in text and "AI WORDS" not in text
    assert report_text({"meta": {"is_test": True}, "summary": {"headline": "x"}}) == ""


# ---------------------------------------------------------------- tools are read-only
def test_agent_tools_cannot_write(tmp_path):
    db = tmp_path / "fg.db"
    con = sqlite3.connect(db)
    con.execute("create table river_gauge_observations (station_id text, recorded_at text, discharge_cumecs real)")
    con.commit()
    con.close()
    tools = AgentTools(daily_report(), kb=None, api_base="http://127.0.0.1:1", exclude_doc_ids=set(), db_path=db)
    with tools._db() as ro, pytest.raises(sqlite3.OperationalError):
        ro.execute("insert into river_gauge_observations values ('X', '2026-01-01', 1)")


def test_satellite_tool_strips_images_and_issues_refs():
    tools = AgentTools(daily_report(), kb=None, api_base="http://127.0.0.1:1", exclude_doc_ids=set())
    content, is_error = tools.execute("get_satellite_check", {"station_id": "Trimmu"})
    payload = json.loads(content)
    assert not is_error and payload["ref"] == "T1" and "image_data_url" not in json.dumps(payload)
    assert tools.refs["T1"]["tool"] == "get_satellite_check"
    content, is_error = tools.execute("get_satellite_check", {"station_id": "NOWHERE"})
    assert is_error and "Unknown station" in content


# ---------------------------------------------------------------- reference checking and integrity
def test_validate_drops_statements_without_issued_references():
    known = {"T1": {"kind": "data"}, "https://ffc.gov.pk/x.pdf#page=2": {"kind": "document"}}
    cleaned, dropped = validate({
        "summary": "s", "uncertainty": {"level": "medium", "reasons": []}, "reviewer_checks": [],
        "evidence": [{"finding": "ok", "relation": "supports", "refs": ["T1", "T9"]},
                     {"finding": "invented", "relation": "context", "refs": ["T9"]},
                     {"finding": "doc", "relation": "context", "refs": [" https://ffc.gov.pk/x.pdf#page=2 "]}],
        "possible_explanations": [{"explanation": "no source", "likelihood": "possible", "refs": []}]}, known)
    assert [e["refs"] for e in cleaned["evidence"]] == [["T1"], ["https://ffc.gov.pk/x.pdf#page=2"]]
    assert cleaned["possible_explanations"] == [] and dropped == 2


def test_facts_digest_ignores_ai_block_but_catches_changes():
    data = daily_report()
    base = facts_digest(data)
    assert facts_digest(data | {"ai_analysis": {"status": "complete"}, "review": {"flags": {}}}) == base
    changed = json.loads(json.dumps(data))
    changed["summary"]["status"] = "Normal"
    assert facts_digest(changed) != base


def test_review_mode_automatic_reports_need_no_review():
    assert review_mode_for("scheduled", "portal") == "none"
    assert review_mode_for("watcher", None) == "none"
    assert review_mode_for("manual", "label") == "label"
    assert review_mode_for("test", None) == "portal"


# ---------------------------------------------------------------- fake Claude
class FakeClient:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append(params)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return item(params) if callable(item) else item


def msg(*content, stop="end_turn"):
    return SimpleNamespace(content=list(content), stop_reason=stop, usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                           stop_details=None)


def tool_use(name, args, uid):
    return SimpleNamespace(type="tool_use", id=uid, name=name, input=args)


def flag():
    return build_daily_flags(daily_report())[0]  # observed flood at Trimmu


def test_agent_loop_submits_checked_findings():
    client = FakeClient([
        msg(tool_use("get_satellite_check", {"station_id": "TRIMMU"}, "u1"), stop="tool_use"),
        msg(tool_use("submit_findings", {
            "summary": "Radar confirms water near Trimmu.", "reviewer_checks": ["Check FFD bulletin"],
            "uncertainty": {"level": "low", "reasons": ["One radar pass"]},
            "evidence": [{"finding": "9.0 km2 of water outside the reference.", "relation": "supports", "refs": ["T1"]},
                         {"finding": "Made-up gauge value.", "relation": "supports", "refs": ["T7"]}],
            "possible_explanations": [{"explanation": "High flood spreading into the floodplain.", "likelihood": "more likely", "refs": ["T1"]}]},
            "u2"), stop="tool_use")])
    result, transcript = analyse_flag(client, flag(), daily_report(), kb=None, api_base="http://127.0.0.1:1", exclude_doc_ids=set())
    assert result["status"] == "complete" and result["dropped_statements"] == 1
    assert [e["refs"] for e in result["evidence"]] == [["T1"]] and "T1" in result["references"]
    assert result["tool_calls"] == 1 and len(transcript) >= 2
    first = client.requests[0]
    assert first["betas"] == ["server-side-fallback-2026-07-01"] and first["fallbacks"] == "default"
    assert any(t.get("name") == "submit_findings" and t.get("strict") for t in first["tools"])
    assert "temperature" not in first


def test_agent_loop_is_bounded(monkeypatch):
    calls = iter(range(1000))
    client = FakeClient([lambda p: msg(tool_use("get_satellite_check", {"station_id": "TRIMMU"}, f"u{next(calls)}"), stop="tool_use")])
    result, _ = analyse_flag(client, flag(), daily_report(), kb=None, api_base="http://127.0.0.1:1", exclude_doc_ids=set())
    from app.core.config import get_settings
    assert result["status"] == "incomplete" and result["turns"] == get_settings().ai_agent_max_turns
    assert len(client.requests) == get_settings().ai_agent_max_turns
    texts = [b.get("text", "") for r in client.requests[-1:] for m in r["messages"] if m["role"] == "user"
             for b in (m["content"] if isinstance(m["content"], list) else []) if isinstance(b, dict)]
    assert any("submit_findings now" in t for t in texts)


def test_agent_refusal_is_reported():
    refused = msg(stop="refusal")
    refused.stop_details = SimpleNamespace(category="cyber")
    result, _ = analyse_flag(FakeClient([refused]), flag(), daily_report(), kb=None, api_base="http://127.0.0.1:1", exclude_doc_ids=set())
    assert result["status"] == "declined" and "declined" in result["note"]


def test_explanation_maps_citations_to_sources(tmp_path):
    (tmp_path / "procedures").mkdir()
    (tmp_path / "procedures" / "plan.md").write_text("At Trimmu Headworks a High flood puts embankments under pressure and the "
                                                     "irrigation department patrols the breaching sections day and night.", encoding="utf-8")
    kb = KnowledgeBase(root=tmp_path, reports_root=tmp_path / "none")
    kb.refresh()
    citation = SimpleNamespace(type="search_result_location", search_result_index=0, start_block_index=0, end_block_index=1,
                               source="x", title="t", cited_text="At Trimmu Headworks a High flood puts embankments under pressure")
    client = FakeClient([msg(SimpleNamespace(type="text", text="Embankments are under pressure at Trimmu.", citations=[citation]),
                             SimpleNamespace(type="text", text=" No further detail.", citations=None))])
    result = explain_flag(client, kb, flag(), {"report_no": "R"}, exclude_doc_ids=set())
    assert result["status"] == "complete" and result["segments"][0]["cites"] == [1]
    assert result["sources"][0]["cited_text"].startswith("At Trimmu") and result["uncited"] == 0
    blocks = client.requests[0]["messages"][0]["content"]
    assert any(b["type"] == "search_result" and b["citations"] == {"enabled": True} for b in blocks)


def test_explanation_without_documents_makes_no_call(tmp_path):
    kb = KnowledgeBase(root=tmp_path, reports_root=tmp_path / "none")
    kb.refresh()
    client = FakeClient([msg()])
    result = explain_flag(client, kb, flag() | {"anchor_terms": ["Nowhereville"], "river": None}, {}, exclude_doc_ids=set())
    assert result["status"] == "no_documents" and client.requests == []


# ---------------------------------------------------------------- review
def test_review_never_changes_report_json(tmp_path, monkeypatch):
    monkeypatch.setattr(review_mod, "render_folder", lambda folder: None)
    report = {"meta": {"report_no": "R"}, "ai_analysis": {"review_mode": "portal", "flags": {"F1": {"explanation": {"status": "complete"}}}}}
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    before = (tmp_path / "report.json").read_bytes()
    review = review_mod.save_decision(tmp_path, "F1", "accepted", "ok", "Duty officer")
    assert review["flags"]["F1"]["decision"] == "accepted"
    assert (tmp_path / "report.json").read_bytes() == before
    assert review_mod.ai_summary(report, review) == {"status": None, "reason": None, "review_mode": "portal", "trigger": None,
                                                     "notes": 1, "reviewed": 1, "to_review": 0}
    with pytest.raises(ValueError):
        review_mod.save_decision(tmp_path, "F9", "accepted", "", "x")
    with pytest.raises(ValueError):
        review_mod.save_decision(tmp_path, "F1", "maybe", "", "x")


def test_block_dict_handles_plain_objects():
    assert agent_mod._block_dict(SimpleNamespace(type="text", text="hi")) == {"type": "text", "text": "hi"}
