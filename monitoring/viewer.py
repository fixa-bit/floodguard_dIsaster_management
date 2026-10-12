"""Loopback-only, read-only SQLite browser for the independent monitoring DB."""

import argparse
import json
import sqlite3
from contextlib import closing
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


GROUPS = {
    "Stations": ["stations"],
    "APIs & Models": ["providers"],
    "Stored Values": ["station_values"],
    "Reference Thresholds": ["thresholds"],
}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def connect(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def tables(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def schema(path):
    with closing(connect(path)) as connection:
        names = tables(connection)
        if set(names) != {name for group in GROUPS.values() for name in group}:
            raise ValueError("Not a monitoring database")
        result = []
        for name in names:
            fields = [dict(row) for row in connection.execute(f"PRAGMA table_info({quote(name)})")]
            relationships = [dict(row) for row in connection.execute(f"PRAGMA foreign_key_list({quote(name)})")]
            indexes = [dict(row) for row in connection.execute(f"PRAGMA index_list({quote(name)})")]
            count = connection.execute(f"SELECT COUNT(*) FROM {quote(name)}").fetchone()[0]
            group = next(group for group, members in GROUPS.items() if name in members)
            result.append({"name": name, "group": group, "count": count,
                           "fields": fields, "relationships": relationships, "indexes": indexes})
        result.sort(key=lambda table: (list(GROUPS).index(table["group"]), table["name"]))
        return {"database": Path(path).name, "readOnly": True, "tables": result,
                "schemaOrder": [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")],
                "versions": [connection.execute("PRAGMA user_version").fetchone()[0]]}


def records(path, table, page=1, size=25, search="", raw=False, order="primary"):
    if page < 1 or page > 100000 or size not in {25, 50, 100} or len(search) > 200 or order not in {"primary", "rowid"}:
        raise ValueError("Invalid pagination or search")
    with closing(connect(path)) as connection:
        if table not in tables(connection):
            raise ValueError("Unknown table")
        fields = [dict(row) for row in connection.execute(f"PRAGMA table_info({quote(table)})")]
        parameters = []
        where = ""
        if search:
            where = " WHERE " + " OR ".join(f"instr(lower(CAST({quote(field['name'])} AS TEXT)), lower(?)) > 0"
                                            for field in fields)
            parameters = [search] * len(fields)
            if table in {"station_values", "thresholds"} and not raw:
                for related, key in [("stations", "station_id"), ("providers", "provider_id")]:
                    where += f" OR EXISTS (SELECT 1 FROM {related} WHERE {related}.id={quote(table)}.{key} AND (instr(lower(name),lower(?))>0 OR instr(lower(code),lower(?))>0))"
                    parameters.extend([search, search])
        count = connection.execute(f"SELECT COUNT(*) FROM {quote(table)}{where}", parameters).fetchone()[0]
        primary_fields = sorted([field for field in fields if field["pk"]], key=lambda field: field["pk"])
        order_by = ", ".join(quote(field["name"]) for field in primary_fields) or quote(fields[0]["name"])
        # SQLite rowid is a sortable key, not a guarantee of physical disk ordering.
        if order == "rowid":
            order_by = "rowid"
        rows = connection.execute(f"SELECT * FROM {quote(table)}{where} ORDER BY {order_by} LIMIT ? OFFSET ?",
                                  parameters + [size, (page - 1) * size]).fetchall()
        decoded = [dict(row) for row in rows]
        if raw:
            # Text transport preserves 64-bit integers beyond JavaScript's safe range.
            decoded = [{key: (None if value is None else
                               "X'" + value.hex() + "'" if isinstance(value, bytes) else str(value))
                        for key, value in row.items()} for row in decoded]
        for row in ([] if raw else decoded):
            for field in fields:
                value = row[field["name"]]
                if field["type"].upper() == "BOOLEAN" and value is not None:
                    row[field["name"]] = bool(value)
                if field["type"].upper() == "JSON" and isinstance(value, str):
                    try:
                        row[field["name"]] = json.loads(value)
                    except ValueError:
                        pass
        columns = [field["name"] for field in fields]
        if table in {"station_values", "thresholds"} and not raw:
            station_ids = list({row["station_id"] for row in decoded})
            provider_ids = list({row["provider_id"] for row in decoded if row["provider_id"] is not None})
            stations = {row["id"]: row for row in connection.execute(
                f"SELECT id,code,name FROM stations WHERE id IN ({','.join('?' for _ in station_ids)})", station_ids)} if station_ids else {}
            providers = {row["id"]: row for row in connection.execute(
                f"SELECT id,code,name,model_version FROM providers WHERE id IN ({','.join('?' for _ in provider_ids)})", provider_ids)} if provider_ids else {}
            columns = ["id", "station", "provider"] + (["model_version"] if table == "station_values" else []) + [name for name in columns if name not in {"id", "station_id", "provider_id"}]
            display_rows = []
            for row in decoded:
                station = stations[row["station_id"]]
                provider = providers.get(row["provider_id"])
                labels = {"station": f"{station['name']} ({station['code']})",
                          "provider": f"{provider['name']} ({provider['code']})" if provider else None,
                          "model_version": provider["model_version"] if provider else None}
                display_rows.append({name: labels[name] if name in labels else row[name] for name in columns})
            decoded = display_rows
        return {"table": table, "rows": decoded, "total": count, "page": page, "size": size,
                "columns": columns, "raw": raw, "orderBy": order_by}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, database, **kwargs):
        self.database = database
        super().__init__(*args, **kwargs)

    def respond(self, status, body, content_type="application/json"):
        payload = json.dumps(body, allow_nan=False).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        # Reject DNS-rebinding hosts; never expose database data cross-origin.
        if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
            self.respond(403, {"error": "Local access only"})
            return
        url = urlparse(self.path)
        try:
            if url.path == "/api/schema":
                self.respond(200, schema(self.database))
            elif url.path == "/api/records":
                query = parse_qs(url.query)
                self.respond(200, records(self.database, query.get("table", [""])[0],
                                          int(query.get("page", ["1"])[0]), int(query.get("size", ["25"])[0]),
                                          query.get("search", [""])[0],
                                          raw=query.get("raw", ["0"])[0] == "1",
                                          order=query.get("order", ["primary"])[0]))
            elif url.path in {"/", "/viewer.css", "/viewer.js", "/diagram.js"}:
                name = {"/": "index.html", "/viewer.css": "viewer.css", "/viewer.js": "viewer.js", "/diagram.js": "diagram.js"}[url.path]
                mime = {"index.html": "text/html; charset=utf-8", "viewer.css": "text/css", "viewer.js": "text/javascript", "diagram.js": "text/javascript"}[name]
                self.respond(200, (Path(__file__).parent / "viewer_assets" / name).read_bytes(), mime)
            else:
                self.respond(404, {"error": "Not found"})
        except (ValueError, sqlite3.Error):
            self.respond(400, {"error": "Unable to read requested monitoring data"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(__file__).parent / "data/monitoring.db")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    schema(args.database)  # Refuse nonexistent/uninitialized databases; never create one.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, database=args.database))
    print(f"Read-only monitoring viewer: http://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
