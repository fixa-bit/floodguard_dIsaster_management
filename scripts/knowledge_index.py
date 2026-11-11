"""Build or search the document index used for report explanations (knowledge/index.db).

Usage:
    .venv/Scripts/python.exe -I scripts/knowledge_index.py                 # refresh (new or changed documents only)
    .venv/Scripts/python.exe -I scripts/knowledge_index.py --rebuild       # rebuild from scratch
    .venv/Scripts/python.exe -I scripts/knowledge_index.py --bulletin      # also fetch and archive today's FFD bulletin
    .venv/Scripts/python.exe -I scripts/knowledge_index.py --list
    .venv/Scripts/python.exe -I scripts/knowledge_index.py --search "Kalabagh Tarbela release"

Downloaded documents are data: their text is extracted and indexed, never run.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.reports.ai.knowledge import KnowledgeBase, fetch_current_bulletin, query_words  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--bulletin", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--search")
    args = parser.parse_args()
    kb = KnowledgeBase()
    if args.rebuild and kb.db_path.exists():
        kb.db_path.unlink()
    if args.bulletin:
        print("Bulletin archived:", fetch_current_bulletin(kb.root))
    print(kb.refresh())
    if args.list:
        for d in kb.documents():
            print(f"{d['kind']:12} {d['chunks']:5} chunks  {d['doc_id']}  {d['note'] or ''}")
    if args.search:
        for h in kb.search(query_words(args.search)):
            print(f"{h.score:6.2f}  {h.title}\n        {h.source}\n        {h.text[:200]}...")


if __name__ == "__main__":
    main()
