import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import func, inspect, select

from .database import create_monitoring_engine, session_factory
from .migrations.runner import upgrade
from .models import Provider, Station, StationValue, Threshold
from .repository import store_value


def import_values(factory, path):
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Import must be a JSON array")
    try:
        with factory.begin() as session:
            return sum(int(store_value(session, **record)[1]) for record in records)
    except Exception:
        logging.getLogger(__name__).error("Import rejected; batch rolled back, prior stored values retained")
        raise


def main():
    parser = argparse.ArgumentParser(description="Station API/model data storage only; no monitoring or alerts")
    parser.add_argument("--database-url")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    provider = commands.add_parser("add-provider")
    provider.add_argument("code")
    provider.add_argument("name")
    provider.add_argument("--kind", choices=["api", "model", "import"], required=True)
    provider.add_argument("--version")
    importer = commands.add_parser("import-json")
    importer.add_argument("path")
    simulator = commands.add_parser("simulate-flow")
    simulator.add_argument("path")
    args = parser.parse_args()
    engine = create_monitoring_engine(args.database_url)
    try:
        factory = session_factory(engine)
        if args.command == "init":
            backup = upgrade(engine)
            from .seed import seed
            with factory.begin() as session:
                seed(session)
            print("Station data store ready: stations, providers, station_values, thresholds. No monitoring logic.")
            if backup:
                print(f"Previous database backup: {backup}")
        else:
            if set(inspect(engine).get_table_names()) != {"stations", "providers", "station_values", "thresholds"}:
                parser.error("Initialize the station data store first")
            if args.command == "add-provider":
                if args.kind == "model" and not args.version:
                    parser.error("A model provider needs --version and a distinct code per version")
                with factory.begin() as session:
                    if session.scalar(select(Provider).where(Provider.code == args.code)) is not None:
                        parser.error("Provider code already exists; use a new code for a different version")
                    session.add(Provider(code=args.code, name=args.name, kind=args.kind, model_version=args.version))
                print(f"Registered provider {args.code}")
            elif args.command == "import-json":
                print(f"Stored {import_values(factory, args.path)} new station values")
            elif args.command == "simulate-flow":
                from .simulation import load_scenarios, store_scenarios
                with factory.begin() as session:
                    result = store_scenarios(session, load_scenarios(args.path))
                providers = ", ".join(result.provider_codes)
                print(f"Stored {result.inserted} new simulated station values from "
                      f"{result.scenarios} scenario(s); provider(s): {providers}")
            else:
                with factory() as session:
                    print(json.dumps({model.__tablename__: session.scalar(select(func.count()).select_from(model))
                                      for model in [Station, Provider, StationValue, Threshold]}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
