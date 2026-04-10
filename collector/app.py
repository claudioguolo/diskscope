#!/usr/bin/env python3

import json
import logging
import os
from csv import DictWriter
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
TOKEN = os.getenv("COLLECTOR_TOKEN", "")
AUTH_HEADER_NAME = os.getenv("AUTH_HEADER_NAME", "Authorization")
AUTH_HEADER_PREFIX = os.getenv("AUTH_HEADER_PREFIX", "Bearer")
OUTPUT_FILE = Path(os.getenv("OUTPUT_FILE", "/data/requests.jsonl"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
POST_PATH = os.getenv("POST_PATH", "/disk-alert")


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("disk-collector")


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_bytes(value: int | str | None) -> str:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        size = 0

    gb_value = size / 1_000_000_000
    return f"{gb_value:.1f} GB"


def extract_collection_date(record: dict) -> str:
    payload = record.get("payload", {})
    timestamp = str(payload.get("timestamp", "") or record.get("received_at", ""))
    if len(timestamp) >= 10:
        return timestamp[:10]
    return ""


def format_date_br(value: str) -> str:
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return f"{value[8:10]}/{value[5:7]}/{value[0:4]}"
    return value or "-"


def clear_records() -> None:
    ensure_parent_dir(OUTPUT_FILE)
    with OUTPUT_FILE.open("w", encoding="utf-8"):
        pass


def load_records() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []

    records = []
    with OUTPUT_FILE.open("r", encoding="utf-8") as handler:
        for line in handler:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                LOGGER.warning("Ignoring invalid JSONL line in %s", OUTPUT_FILE)

    records.sort(key=lambda item: item.get("received_at", ""), reverse=True)
    return records


def filter_records(
    records: list[dict],
    status_filter: str,
    date_from: str,
    date_to: str,
) -> list[dict]:
    filtered = []

    for record in records:
        collection_date = extract_collection_date(record)

        if status_filter == "warning":
            if str(record.get("payload", {}).get("status", "")).upper() != "WARNING":
                continue

        if date_from and collection_date and collection_date < date_from:
            continue

        if date_to and collection_date and collection_date > date_to:
            continue

        if (date_from or date_to) and not collection_date:
            continue

        filtered.append(record)

    return filtered


def build_query_string(status_filter: str, date_from: str, date_to: str, output_format: str = "") -> str:
    query = {}

    if status_filter == "warning":
        query["status"] = "warning"

    if date_from:
        query["date_from"] = date_from

    if date_to:
        query["date_to"] = date_to

    if output_format:
        query["format"] = output_format

    encoded = urlencode(query)
    if encoded:
        return f"/?{encoded}"
    return "/"


def build_csv(records: list[dict]) -> str:
    buffer = StringIO()
    writer = DictWriter(
        buffer,
        fieldnames=[
            "received_at",
            "remote_addr",
            "hostname",
            "ip",
            "os",
            "status",
            "detection_state",
            "unused_disks_count",
            "unused_capacity_total_bytes",
            "unused_capacity_total_human",
            "unused_disks",
            "timestamp",
        ],
    )
    writer.writeheader()

    for record in records:
        payload = record.get("payload", {})
        unused_disks = payload.get("unused_disks", [])
        if isinstance(unused_disks, list):
            unused_disks_text = ", ".join(str(item) for item in unused_disks)
        else:
            unused_disks_text = str(unused_disks)

        writer.writerow(
            {
                "received_at": record.get("received_at", ""),
                "remote_addr": record.get("remote_addr", ""),
                "hostname": payload.get("hostname", ""),
                "ip": payload.get("ip", ""),
                "os": payload.get("os", ""),
                "status": payload.get("status", ""),
                "detection_state": payload.get("detection_state", ""),
                "unused_disks_count": payload.get("unused_disks_count", ""),
                "unused_capacity_total_bytes": payload.get("unused_capacity_total_bytes", ""),
                "unused_capacity_total_human": payload.get("unused_capacity_total_human", ""),
                "unused_disks": unused_disks_text,
                "timestamp": payload.get("timestamp", ""),
            }
        )

    return buffer.getvalue()


def render_table(
    records: list[dict],
    status_filter: str,
    all_count: int,
    warning_count: int,
    date_from: str,
    date_to: str,
) -> str:
    rows = []

    for record in records:
        payload = record.get("payload", {})
        status = str(payload.get("status", "-"))
        detection_state = str(payload.get("detection_state", "-"))
        unused_disks = payload.get("unused_disks", [])
        unused_disks_detail = payload.get("unused_disks_detail", [])
        total_capacity_human = str(
            payload.get("unused_capacity_total_human")
            or format_bytes(payload.get("unused_capacity_total_bytes", 0))
        )
        if isinstance(unused_disks, list):
            unused_disks_text = ", ".join(str(item) for item in unused_disks) or "-"
        else:
            unused_disks_text = str(unused_disks) or "-"

        if isinstance(unused_disks_detail, list) and unused_disks_detail:
            detail_parts = []
            for item in unused_disks_detail:
                if not isinstance(item, dict):
                    continue
                detail_parts.append(
                    f"{item.get('name', '-')} ({item.get('size_human') or format_bytes(item.get('size_bytes', 0))})"
                )
            if detail_parts:
                unused_disks_text = ", ".join(detail_parts)

        badge_class = "warning" if status.upper() == "WARNING" else "ok"
        status_html = (
            f'<span class="badge {escape(badge_class)}">{escape(status)}</span>'
        )
        detection_html = f'<span class="subtle">{escape(detection_state)}</span>'
        host_block = """
        <div class="host-cell">
          <strong>{hostname}</strong>
          <span>{ip_addr}</span>
        </div>
        """.format(
            hostname=escape(str(payload.get("hostname", "-"))),
            ip_addr=escape(str(payload.get("ip", "-"))),
        )
        source_block = """
        <div class="source-cell">
          <strong>{received_at}</strong>
          <span>{remote_addr}</span>
        </div>
        """.format(
            received_at=escape(format_date_br(str(record.get("received_at", "-")))),
            remote_addr=escape(str(record.get("remote_addr", "-"))),
        )
        inventory_block = """
        <div class="inventory-cell">
          <span class="count">{unused_count}</span>
          <span class="subtle">{total_capacity}</span>
          <span class="subtle">{unused_disks}</span>
        </div>
        """.format(
            unused_count=escape(str(payload.get("unused_disks_count", "-"))),
            total_capacity=escape(total_capacity_human),
            unused_disks=escape(unused_disks_text),
        )

        rows.append(
            """
            <tr>
              <td>{source}</td>
              <td>{host}</td>
              <td>{os_name}</td>
              <td>{status}</td>
              <td>{detection_state}</td>
              <td>{inventory}</td>
              <td>{timestamp}</td>
            </tr>
            """.format(
                source=source_block,
                host=host_block,
                os_name=escape(str(payload.get("os", "-"))),
                status=status_html,
                detection_state=detection_html,
                inventory=inventory_block,
                timestamp=escape(str(payload.get("timestamp", "-"))),
            )
        )

    tbody = "\n".join(rows) if rows else (
        '<tr><td colspan="7" class="empty">Nenhum dado coletado ate o momento.</td></tr>'
    )

    total_visible = len(records)
    unused_capacity_total = sum(
        int(record.get("payload", {}).get("unused_capacity_total_bytes", 0) or 0)
        for record in records
    )
    occurrence_percent = 0.0
    if all_count > 0:
        occurrence_percent = (warning_count / all_count) * 100
    all_link_class = "filter-link active" if status_filter != "warning" else "filter-link"
    warning_link_class = "filter-link active" if status_filter == "warning" else "filter-link"
    all_href = build_query_string("all", date_from, date_to)
    warning_href = build_query_string("warning", date_from, date_to)
    csv_href = build_query_string(status_filter, date_from, date_to, "csv")
    clear_filters_href = "/"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DiskScope</title>
    <style>
      :root {{
        --bg: #f5f1e8;
        --panel: #fffaf2;
        --line: #d8cdb8;
        --text: #1f2933;
        --muted: #6b7280;
        --accent: #a44a3f;
        --ok: #256f4c;
        --warn: #9a6700;
      }}
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at top left, rgba(164, 74, 63, 0.16), transparent 28%),
          linear-gradient(180deg, #f7f2e9 0%, #efe7da 100%);
      }}
      .page {{
        max-width: 1400px;
        margin: 0 auto;
        padding: 22px 16px 36px;
      }}
      .hero {{
        margin-bottom: 12px;
      }}
      h1 {{
        margin: 0 0 4px;
        font-size: clamp(1.7rem, 3vw, 2.5rem);
        line-height: 1;
        letter-spacing: -0.04em;
      }}
      .subtitle {{
        margin: 0;
        color: var(--muted);
        font-size: 0.95rem;
      }}
      .meta {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin: 14px 0 16px;
      }}
      .toolbar {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin: 0 0 14px;
      }}
      .toolbar-form {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
        margin: 0 0 14px;
      }}
      .toolbar-form input[type="date"] {{
        padding: 8px 10px;
        border: 1px solid var(--line);
        border-radius: 10px;
        background: rgba(255, 250, 242, 0.92);
        color: var(--text);
        font: inherit;
        font-size: 0.82rem;
      }}
      .toolbar-form button,
      .toolbar-form a {{
        padding: 8px 11px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: rgba(255, 250, 242, 0.92);
        color: var(--text);
        text-decoration: none;
        font: inherit;
        font-size: 0.82rem;
        font-weight: 600;
        cursor: pointer;
      }}
      .toolbar-form .danger {{
        border-color: rgba(164, 74, 63, 0.3);
        background: rgba(164, 74, 63, 0.12);
      }}
      .filter-link {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 7px 11px;
        border: 1px solid var(--line);
        border-radius: 999px;
        background: rgba(255, 250, 242, 0.92);
        color: var(--text);
        text-decoration: none;
        font-size: 0.82rem;
        font-weight: 600;
      }}
      .filter-link.active {{
        border-color: rgba(164, 74, 63, 0.4);
        background: rgba(164, 74, 63, 0.12);
      }}
      .filter-link.export {{
        margin-left: auto;
        background: rgba(37, 111, 76, 0.1);
        border-color: rgba(37, 111, 76, 0.2);
      }}
      .card {{
        background: rgba(255, 250, 242, 0.9);
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 10px 12px;
        min-width: 150px;
        box-shadow: 0 10px 24px rgba(73, 47, 32, 0.08);
      }}
      .card strong {{
        display: block;
        font-size: 1.2rem;
        margin-top: 4px;
      }}
      .table-wrap {{
        overflow-x: auto;
        background: rgba(255, 250, 242, 0.92);
        border: 1px solid var(--line);
        border-radius: 16px;
        box-shadow: 0 16px 36px rgba(73, 47, 32, 0.1);
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        min-width: 980px;
      }}
      th, td {{
        padding: 10px 12px;
        text-align: left;
        border-bottom: 1px solid rgba(216, 205, 184, 0.7);
        vertical-align: top;
      }}
      th {{
        position: sticky;
        top: 0;
        background: #f1e6d5;
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }}
      td {{
        font-size: 0.78rem;
        line-height: 1.2;
      }}
      tr:hover td {{
        background: rgba(164, 74, 63, 0.05);
      }}
      .host-cell,
      .source-cell,
      .inventory-cell {{
        display: grid;
        gap: 2px;
      }}
      .host-cell strong,
      .source-cell strong {{
        font-size: 0.8rem;
      }}
      .host-cell span,
      .source-cell span,
      .subtle {{
        color: var(--muted);
        font-size: 0.7rem;
      }}
      .inventory-cell .count {{
        font-weight: 700;
        font-size: 0.8rem;
      }}
      .badge {{
        display: inline-block;
        padding: 2px 7px;
        border-radius: 999px;
        font-size: 0.66rem;
        font-weight: 700;
      }}
      .badge.ok {{
        color: var(--ok);
        background: rgba(37, 111, 76, 0.12);
      }}
      .badge.warning {{
        color: var(--warn);
        background: rgba(154, 103, 0, 0.14);
      }}
      .empty {{
        text-align: center;
        color: var(--muted);
        padding: 30px 16px;
      }}
      @media (max-width: 720px) {{
        .page {{
          padding: 24px 14px 40px;
        }}
        .card {{
          min-width: 140px;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <section class="hero">
        <h1>DiskScope</h1>
        <p class="subtitle">Visao consolidada dos dados enviados pelos scripts executados via Satellite.</p>
      </section>
      <section class="meta">
        <div class="card">
          <span>Registros visiveis</span>
          <strong>{total_visible}</strong>
        </div>
        <div class="card">
          <span>Warnings</span>
          <strong>{warning_count}</strong>
        </div>
        <div class="card">
          <span>% hosts com ocorrencia</span>
          <strong>{occurrence_percent:.1f}%</strong>
        </div>
        <div class="card">
          <span>Capacidade nao usada</span>
          <strong>{escape(format_bytes(unused_capacity_total))}</strong>
        </div>
        <div class="card">
          <span>Atualizado em</span>
          <strong>{escape(format_date_br(utc_now()))}</strong>
        </div>
      </section>
      <section class="toolbar">
        <a class="{all_link_class}" href="{all_href}">Todos <strong>{all_count}</strong></a>
        <a class="{warning_link_class}" href="{warning_href}">Somente WARNING <strong>{warning_count}</strong></a>
        <a class="filter-link export" href="{csv_href}">Exportar CSV</a>
      </section>
      <form class="toolbar-form" method="get" action="/">
        <input type="hidden" name="status" value="{escape(status_filter if status_filter == 'warning' else 'all')}">
        <input type="date" name="date_from" value="{escape(date_from)}" aria-label="Data inicial">
        <input type="date" name="date_to" value="{escape(date_to)}" aria-label="Data final">
        <button type="submit">Filtrar por data</button>
        <a href="{clear_filters_href}">Limpar filtros</a>
      </form>
      <form class="toolbar-form" method="post" action="/admin/clear" onsubmit="return confirm('Limpar toda a base de dados coletada?');">
        <button class="danger" type="submit">Limpar base de dados</button>
      </form>
      <section class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Recebimento</th>
              <th>Host</th>
              <th>Sistema</th>
              <th>Status</th>
              <th>Coleta</th>
              <th>Discos</th>
              <th>Timestamp do host</th>
            </tr>
          </thead>
          <tbody>
            {tbody}
          </tbody>
        </table>
      </section>
    </main>
  </body>
</html>"""


class CollectorHandler(BaseHTTPRequestHandler):
    server_version = "DiskCollector/1.0"

    def do_POST(self) -> None:
        if self.path != POST_PATH:
            if self.path == "/admin/clear":
                clear_records()
                LOGGER.warning("Collected data cleared from UI by %s", self.client_address[0])
                self.redirect("/")
                return

            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "path_not_found"})
            return

        if TOKEN:
            expected = f"{AUTH_HEADER_PREFIX} {TOKEN}".strip()
            received = self.headers.get(AUTH_HEADER_NAME, "")
            if received != expected:
                LOGGER.warning("Unauthorized request from %s", self.client_address[0])
                self.respond_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return

        content_length = self.headers.get("Content-Length", "0")
        try:
            body_size = int(content_length)
        except ValueError:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return

        raw_body = self.rfile.read(body_size)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        record = {
            "received_at": utc_now(),
            "remote_addr": self.client_address[0],
            "payload": payload,
        }

        ensure_parent_dir(OUTPUT_FILE)
        with OUTPUT_FILE.open("a", encoding="utf-8") as handler:
            handler.write(json.dumps(record, ensure_ascii=True) + "\n")

        LOGGER.info(
            "Payload received from host=%s status=%s unused_disks_count=%s",
            payload.get("hostname", "unknown"),
            payload.get("status", "unknown"),
            payload.get("unused_disks_count", "unknown"),
        )
        self.respond_json(HTTPStatus.OK, {"result": "accepted"})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            query = parse_qs(parsed.query)
            status_filter = query.get("status", ["all"])[0].lower()
            date_from = query.get("date_from", [""])[0]
            date_to = query.get("date_to", [""])[0]
            output_format = query.get("format", ["html"])[0].lower()
            all_records = load_records()
            visible_records = filter_records(all_records, status_filter, date_from, date_to)

            if output_format == "csv":
                self.respond_csv(HTTPStatus.OK, build_csv(visible_records))
                return

            warning_count = len(filter_records(all_records, "warning", date_from, date_to))
            self.respond_html(
                HTTPStatus.OK,
                render_table(
                    visible_records,
                    status_filter,
                    len(filter_records(all_records, "all", date_from, date_to)),
                    warning_count,
                    date_from,
                    date_to,
                ),
            )
            return

        if parsed.path == "/health":
            self.respond_json(HTTPStatus.OK, {"status": "ok", "time": utc_now()})
            return

        self.respond_json(HTTPStatus.NOT_FOUND, {"error": "path_not_found"})

    def log_message(self, fmt: str, *args) -> None:
        LOGGER.info("%s - %s", self.client_address[0], fmt % args)

    def respond_json(self, status: HTTPStatus, payload: dict) -> None:
        response = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def respond_html(self, status: HTTPStatus, html: str) -> None:
        response = html.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def respond_csv(self, status: HTTPStatus, csv_content: str) -> None:
        response = csv_content.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="diskscope.csv"')
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER.value)
        self.send_header("Location", location)
        self.end_headers()


def main() -> None:
    ensure_parent_dir(OUTPUT_FILE)
    server = ThreadingHTTPServer((HOST, PORT), CollectorHandler)
    LOGGER.info("Starting collector on %s:%s path=%s", HOST, PORT, POST_PATH)
    server.serve_forever()


if __name__ == "__main__":
    main()
