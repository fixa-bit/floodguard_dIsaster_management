"""Document knowledge base for report explanations (RAG). Documents only, never readings.

Corpus (all under settings.knowledge_dir unless noted):
  procedures/   public plans, manuals and classifications (sources.json records where each came from)
  ffc_reports/  Federal Flood Commission daily flood situation reports
  bulletins/    FFD bulletins, archived automatically when fetched (archive_bulletin)
  method notes  FloodGuard docs that explain how the data behaves (METHOD_NOTES, repo paths)
  reports/      past FloodGuard reports: code-generated content only, never test events,
                simulated items, AI text or reviewer notes, so the AI never cites its own output.
Index: SQLite FTS5 (BM25) in <knowledge_dir>/index.db, refreshed incrementally by content hash.
Downloaded documents are data: their text is extracted, never executed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from app.reports.collector import ROOT

logger = logging.getLogger(__name__)

METHOD_NOTES = [
    "docs/reports/daily_report_spec.md",
    "docs/reports/flood_event_report_spec.md",
    "docs/station-discharge-sources.md",
    "docs/google-flood-hub.md",
    "features/ffd-glofas-discharge-window-alignment.md",
    "features/upstream-flood-threshold-lines.md",
]
KIND_NAMES = {"procedure": "Plan or procedure", "ffc_report": "FFC flood report", "bulletin": "FFD bulletin",
              "method_note": "FloodGuard method note", "past_report": "Past FloodGuard report"}
CHUNK_CHARS = 1000
OVERLAP_CHARS = 150
RECENT_KINDS = {"bulletin", "past_report", "ffc_report"}
STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "were", "has", "have", "at", "in", "on", "of", "to",
             "a", "an", "is", "be", "by", "or", "as", "it", "its", "into", "than", "then", "what", "why", "how", "does", "did"}


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    source: str
    title: str
    kind: str
    published: str | None
    page: int | None
    url: str | None
    text: str
    score: float

    def as_dict(self) -> dict:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id, "source": self.source, "title": self.title, "kind": self.kind,
                "kind_name": KIND_NAMES.get(self.kind, self.kind), "published": self.published, "page": self.page, "url": self.url}


def _split(text: str) -> list[str]:
    """Split text into chunks of about CHUNK_CHARS on paragraph or sentence breaks, with overlap."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=#)", text) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        while len(p) > CHUNK_CHARS * 1.5:  # very long paragraph: cut at a sentence end
            cut = p.rfind(". ", 0, CHUNK_CHARS)
            cut = cut + 1 if cut > CHUNK_CHARS // 3 else CHUNK_CHARS
            if current:
                chunks.append(current)
                current = ""
            chunks.append(p[:cut].strip())
            p = p[max(cut - OVERLAP_CHARS, 0):].strip()
        if len(current) + len(p) + 1 > CHUNK_CHARS and current:
            chunks.append(current)
            current = current[-OVERLAP_CHARS:].split(" ", 1)[-1] + " " + p if OVERLAP_CHARS else p
        else:
            current = f"{current}\n{p}" if current else p
    if current:
        chunks.append(current)
    return [" ".join(c.split()) for c in chunks if len(c.strip()) >= 40]


def _pdf_pages(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader
    pages = []
    for number, page in enumerate(PdfReader(str(path)).pages, 1):
        try:
            pages.append((number, page.extract_text() or ""))
        except Exception:  # a broken page must not stop the document
            pages.append((number, ""))
    return pages


def _docx_text(path: Path) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        root = ElementTree.fromstring(zf.read("word/document.xml"))
    paragraphs = ["".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t")) for p in root.iter(f"{{{ns['w']}}}p")]
    return "\n\n".join(p for p in paragraphs if p.strip())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class KnowledgeBase:
    def __init__(self, root: Path | None = None, reports_root: Path | None = None):
        from app.core.config import get_settings
        configured = Path(get_settings().knowledge_dir)
        self.root = root or (configured if configured.is_absolute() else ROOT / configured)
        self.reports_root = reports_root or ROOT / "reports"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "index.db"
        self._catalog = self._load_catalog()

    # ------------------------------------------------------------------ storage
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("create table if not exists docs(doc_id text primary key, kind text, title text, url text, "
                    "published text, sha256 text, chunks integer, indexed_at text, note text)")
        con.execute("create virtual table if not exists chunks using fts5(chunk_id unindexed, doc_id unindexed, source unindexed, "
                    "title, kind unindexed, published unindexed, page unindexed, url unindexed, text, tokenize='porter unicode61')")
        return con

    def _load_catalog(self) -> dict[str, dict]:
        path = self.root / "sources.json"
        try:
            return {d["file"]: d for d in json.loads(path.read_text(encoding="utf-8")).get("documents", [])}
        except (OSError, ValueError, KeyError):
            return {}

    # ------------------------------------------------------------------ corpus
    def _file_docs(self) -> list[dict]:
        docs = []
        for folder, kind in (("procedures", "procedure"), ("ffc_reports", "ffc_report"), ("bulletins", "bulletin")):
            for path in sorted((self.root / folder).glob("*")):
                if path.suffix.lower() not in (".pdf", ".docx", ".md", ".txt") or not path.is_file():
                    continue
                rel = path.relative_to(self.root).as_posix()
                meta = self._catalog.get(rel, {})
                title = meta.get("title") or path.stem.replace("_", " ")
                if meta.get("publisher"):
                    title = f"{title} ({meta['publisher']})"
                published = None
                match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
                if match:
                    published = match.group(1)
                elif meta.get("year"):
                    published = f"{meta['year']}-01-01"
                docs.append({"doc_id": f"kb/{rel}", "kind": kind, "title": title, "url": meta.get("url"), "path": path,
                             "published": published})
        for rel in METHOD_NOTES:
            path = ROOT / rel
            if path.is_file():
                docs.append({"doc_id": f"repo/{rel}", "kind": "method_note", "title": f"FloodGuard method note: {path.stem.replace('_', ' ')}",
                             "url": None, "path": path, "published": None})
        return docs

    def _report_docs(self) -> list[dict]:
        docs, latest_daily = [], {}
        for path in sorted(self.reports_root.glob("daily/*/report.json")):
            latest_daily[path.parent.name[:10]] = path  # one run per day: the last one
        paths = list(latest_daily.values()) + sorted(p for p in self.reports_root.glob("events/*/v*/report.json"))
        for path in paths:  # events/test/... is never matched by events/*/v*/
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            text = report_text(data)
            if not text:
                continue
            meta = data.get("meta", {})
            docs.append({"doc_id": f"report/{path.parent.relative_to(self.reports_root).as_posix()}", "kind": "past_report",
                         "title": f"FloodGuard report {meta.get('report_no', path.parent.name)}", "url": None, "text": text,
                         "published": _report_date(data, path)})
        return docs

    def _extract(self, doc: dict) -> tuple[list[tuple[int | None, str]], str | None]:
        if "text" in doc:
            return [(None, doc["text"])], None
        path: Path = doc["path"]
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages = _pdf_pages(path)
            if not any(t.strip() for _n, t in pages):
                return [], "No text layer (scanned PDF); not searchable"
            return [(n, t) for n, t in pages if t.strip()], None
        if suffix == ".docx":
            return [(None, _docx_text(path))], None
        return [(None, path.read_text(encoding="utf-8", errors="replace"))], None

    # ------------------------------------------------------------------ indexing
    def refresh(self) -> dict:
        """Index new or changed documents and drop removed ones. Returns counts."""
        docs = self._file_docs() + self._report_docs()
        stats = {"documents": len(docs), "indexed": 0, "unchanged": 0, "removed": 0, "no_text": 0}
        with self._connect() as con:
            known = {r["doc_id"]: r["sha256"] for r in con.execute("select doc_id, sha256 from docs")}
            current = set()
            for doc in docs:
                current.add(doc["doc_id"])
                raw = doc["text"].encode("utf-8") if "text" in doc else doc["path"].read_bytes()
                digest = _sha256(raw)
                if known.get(doc["doc_id"]) == digest:
                    stats["unchanged"] += 1
                    continue
                try:
                    parts, note = self._extract(doc)
                except Exception as exc:  # a bad file must not stop the index
                    logger.warning("Could not read %s: %s", doc["doc_id"], exc)
                    parts, note = [], f"Could not read: {type(exc).__name__}"
                con.execute("delete from chunks where doc_id = ?", (doc["doc_id"],))
                count = 0
                for page, text in parts:
                    for i, chunk in enumerate(_split(text)):
                        count += 1
                        chunk_id = f"{doc['doc_id']}#{page or 0}.{i}"
                        source = (f"{doc['url']}#page={page}" if page else doc["url"]) if doc.get("url") else \
                            f"kb://{doc['doc_id']}" + (f"#page={page}" if page else "")
                        title = doc["title"] + (f", page {page}" if page else "")
                        con.execute("insert into chunks values (?,?,?,?,?,?,?,?,?)",
                                    (chunk_id, doc["doc_id"], source, title, doc["kind"], doc.get("published"), page, doc.get("url"), chunk))
                stats["no_text"] += 1 if note and not count else 0
                con.execute("insert or replace into docs values (?,?,?,?,?,?,?,?,?)",
                            (doc["doc_id"], doc["kind"], doc["title"], doc.get("url"), doc.get("published"), digest, count,
                             datetime.now(timezone.utc).isoformat(), note))
                stats["indexed"] += 1
            for doc_id in set(known) - current:
                con.execute("delete from chunks where doc_id = ?", (doc_id,))
                con.execute("delete from docs where doc_id = ?", (doc_id,))
                stats["removed"] += 1
        return stats

    def documents(self) -> list[dict]:
        with self._connect() as con:
            return [dict(r) for r in con.execute("select doc_id, kind, title, url, published, chunks, note from docs order by kind, doc_id")]

    # ------------------------------------------------------------------ search
    def search(self, terms: list[str], anchors: list[str] | None = None, limit: int = 6, per_doc: int = 2,
               exclude_doc_ids: set[str] | None = None, now: datetime | None = None) -> list[Hit]:
        """BM25 search over the terms. When anchors (station, district or river names) are given, a passage
        must mention one of them, so results stay about the flagged place."""
        words = [t.strip() for t in terms if t and t.strip()]
        if not words:
            return []
        query = " OR ".join('"' + w.replace('"', " ") + '"' for w in words)
        now = now or datetime.now(timezone.utc)
        with self._connect() as con:
            try:
                rows = con.execute("select chunk_id, doc_id, source, title, kind, published, page, url, text, bm25(chunks, 0, 0, 0, 3.0, 0, 0, 0, 0, 1.0) as score "
                                   "from chunks where chunks match ? order by score limit 120", (query,)).fetchall()
            except sqlite3.OperationalError as exc:
                logger.warning("Knowledge search failed for %r: %s", query, exc)
                return []
        lowered_anchors = [a.lower() for a in (anchors or []) if a]
        hits = []
        for r in rows:
            if exclude_doc_ids and r["doc_id"] in exclude_doc_ids:
                continue
            text_l = f"{r['title']} {r['text']}".lower()
            if lowered_anchors and not any(a in text_l for a in lowered_anchors):
                continue
            score = -float(r["score"])  # bm25: lower is better
            if r["kind"] in RECENT_KINDS and r["published"]:
                try:
                    age = now - datetime.fromisoformat(r["published"]).replace(tzinfo=timezone.utc)
                    if age <= timedelta(days=30):
                        score *= 1.3
                except ValueError:
                    pass
            hits.append(Hit(r["chunk_id"], r["doc_id"], r["source"], r["title"], r["kind"], r["published"],
                            int(r["page"]) if r["page"] not in (None, "") else None, r["url"], r["text"], score))
        hits.sort(key=lambda h: -h.score)
        chosen, per = [], {}
        for h in hits:
            if per.get(h.doc_id, 0) >= per_doc:
                continue
            per[h.doc_id] = per.get(h.doc_id, 0) + 1
            chosen.append(h)
            if len(chosen) >= limit:
                break
        return chosen


def query_words(text: str) -> list[str]:
    """Free-text query (from the agent) to search terms."""
    words = re.findall(r"[A-Za-z][A-Za-z.\-]{2,}", text)
    return [w for w in dict.fromkeys(words) if w.lower() not in STOPWORDS][:16]


def _report_date(data: dict, path: Path) -> str | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", path.parent.name)
    if match:
        return match.group(1)
    generated = (data.get("meta") or {}).get("generated", "")
    try:
        return datetime.strptime(generated[:11].strip(), "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def report_text(data: dict) -> str:
    """Code-generated content of a past report, for search. Never AI text, reviews or simulated items."""
    meta, summary = data.get("meta", {}), data.get("summary", {})
    if meta.get("is_test"):
        return ""
    lines = []
    if "event" in data:
        e = data["event"]
        lines.append(f"FloodGuard Flood Event Report {meta.get('report_no')} ({meta.get('reason')}), issued {meta.get('generated')}. "
                     f"{e.get('river')} flood event, highest level {e.get('level_name')}, status {e.get('status')}.")
        for s in e.get("signals", []):
            if "sim" not in (s.get("sources") or []) and not s.get("simulated"):
                lines.append(f"Signal: {s.get('detail')}")
    else:
        lines.append(f"FloodGuard Daily Flood Situation Report {meta.get('report_no')}, {meta.get('period', '')}. "
                     f"National status: {summary.get('status')}.")
    if summary.get("headline"):
        lines.append(summary["headline"])
    for c in summary.get("concerns", []):
        if "sim" not in (c.get("sources") or []):
            lines.append(f"Concern: {c.get('text')}")
    flooded = [s for s in data.get("stations", []) if s.get("category") not in (None, "Below low", "Unavailable") and not s.get("simulated")]
    for s in flooded:
        lines.append(f"{s['name']} ({s.get('river')}): {s['category']}, {s.get('discharge') or 0:,.0f} cumecs, observed {s.get('observed_at')}.")
    for f in data.get("flags", []):
        if not f.get("simulated"):
            m, c = f.get("measured", {}), f.get("category", {})
            lines.append(f"Flagged: {f.get('title')}. Measured {m.get('value')} {('(' + m['detail'] + ')') if m.get('detail') else ''}. "
                         f"Category: {c.get('label')}.")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------- FFD bulletins
BULLETIN_URL = "https://ffd.pmd.gov.pk/bulletin"


def archive_bulletin(html: str, root: Path | None = None) -> Path | None:
    """Save the text of an FFD bulletin once per bulletin number. Best effort: never raises."""
    try:
        from app.services.ffd_bulletin_service import BulletinParser
        parser = BulletinParser()
        parser.feed(html)
        text = " ".join(" ".join(parser.text).split())
        match = re.search(r"BULLETIN\s+No:\s*([\w/-]+)\s+Dated:\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[-\s]+(\d{4})", text)
        if not match:
            return None
        issued = datetime.strptime(f"{match[2]} {match[3]} {match[4]}", "%d %B %Y").date().isoformat()
        number = re.sub(r"[^\w-]", "-", match[1])
        if root is None:
            root = KnowledgeBase().root
        folder = root / "bulletins"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"ffd_bulletin_{number}_{issued}.txt"
        if not path.exists():
            body = text[match.start():][:20000]
            path.write_text(f"FFD Flood Bulletin No. {match[1]}, dated {issued}. Source: {parser.permalink}\n\n{body}\n", encoding="utf-8")
        return path
    except Exception:  # archiving must never break bulletin parsing
        logger.exception("Could not archive the FFD bulletin")
        return None


def fetch_current_bulletin(root: Path | None = None) -> Path | None:
    """Fetch and archive today's FFD bulletin (one GET). Best effort."""
    try:
        import httpx
        response = httpx.get(BULLETIN_URL, timeout=15, follow_redirects=True)
        response.raise_for_status()
        return archive_bulletin(response.text, root)
    except Exception as exc:
        logger.info("FFD bulletin not archived: %s", exc)
        return None
