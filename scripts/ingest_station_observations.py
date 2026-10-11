import argparse
import asyncio
import logging

from app.db.session import SessionLocal
from app.services.station_ingestion import ingest_report, import_csv
from scripts.migrate_station_observations import main as migrate


def main():
    parser = argparse.ArgumentParser(description="Import official daily INFLOW readings; never model output.")
    parser.add_argument("--url", default="https://ffd.pmd.gov.pk/bulletin")
    parser.add_argument("--csv", help="Timezone-aware observed_at; all values are inflow cusecs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        migrate()
        with SessionLocal() as db:
            if args.csv:
                with open(args.csv, encoding="utf-8-sig", newline="") as stream:
                    count = import_csv(db, stream)
            else:
                count = asyncio.run(ingest_report(db, args.url))
        logging.info("Stored %s official inflow readings", count)
    except Exception:
        logging.exception("Daily ingestion failed; existing observations retained")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
