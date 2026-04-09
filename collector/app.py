#!/usr/bin/env python3

import json
import logging
import os
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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


def render_table(records: list[dict]) -> str:
    rows = []

    for record in records:
        payload = record.get("payload", {})
        status = str(payload.get("status", "-"))
        unused_disks = payload.get("unused_disks", [])
        if isinstance(unused_disks, list):
            unused_disks_text = ", ".join(str(item) for item in unused_disks) or "-"
        else:
            unused_disks_text = str(unused_disks) or "-"

        badge_class = "warning" if status.upper() == "WARNING" else "ok"
        status_html = (
            f'<span class="badge {escape(badge_class)}">{escape(status)}</span>'
        )

        rows.append(
            """
            <tr>
              <td>{received_at}</td>
              <td>{remote_addr}</td>
              <td>{hostname}</td>
              <td>{ip_addr}</td>
              <td>{os_name}</td>
              <td>{status}</td>
              <td>{detection_state}</td>
              <td>{unused_count}</td>
              <td>{unused_disks}</td>
              <td>{timestamp}</td>
            </tr>
            """.format(
                received_at=escape(str(record.get("received_at", "-"))),
                remote_addr=escape(str(record.get("remote_addr", "-"))),
                hostname=escape(str(payload.get("hostname", "-"))),
                ip_addr=escape(str(payload.get("ip", "-"))),
                os_name=escape(str(payload.get("os", "-"))),
                status=status_html,
                detection_state=escape(str(payload.get("detection_state", "-"))),
                unused_count=escape(str(payload.get("unused_disks_count", "-"))),
                unused_disks=escape(unused_disks_text),
                timestamp=escape(str(payload.get("timestamp", "-"))),
            )
        )

    tbody = "\n".join(rows) if rows else (
        '<tr><td colspan="10" class="empty">Nenhum dado coletado ate o momento.</td></tr>'
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Coletor de Discos</title>
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
        padding: 32px 20px 48px;
      }}
      .hero {{
        margin-bottom: 20px;
      }}
      h1 {{
        margin: 0 0 8px;
        font-size: clamp(2rem, 4vw, 3.2rem);
        line-height: 1;
        letter-spacing: -0.04em;
      }}
      .subtitle {{
        margin: 0;
        color: var(--muted);
        font-size: 1rem;
      }}
      .meta {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin: 18px 0 24px;
      }}
      .card {{
        background: rgba(255, 250, 242, 0.9);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 14px 16px;
        min-width: 180px;
        box-shadow: 0 14px 35px rgba(73, 47, 32, 0.08);
      }}
      .card strong {{
        display: block;
        font-size: 1.5rem;
        margin-top: 6px;
      }}
      .table-wrap {{
        overflow-x: auto;
        background: rgba(255, 250, 242, 0.92);
        border: 1px solid var(--line);
        border-radius: 18px;
        box-shadow: 0 20px 50px rgba(73, 47, 32, 0.1);
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
        min-width: 1100px;
      }}
      th, td {{
        padding: 14px 16px;
        text-align: left;
        border-bottom: 1px solid rgba(216, 205, 184, 0.7);
        vertical-align: top;
      }}
      th {{
        position: sticky;
        top: 0;
        background: #f1e6d5;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }}
      tr:hover td {{
        background: rgba(164, 74, 63, 0.05);
      }}
      .badge {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
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
        <h1>Coletor de Discos</h1>
        <p class="subtitle">Visao consolidada dos dados enviados pelos scripts executados via Satellite.</p>
      </section>
      <section class="meta">
        <div class="card">
          <span>Registros</span>
          <strong>{len(records)}</strong>
        </div>
        <div class="card">
          <span>Atualizado em</span>
          <strong>{escape(utc_now())}</strong>
        </div>
      </section>
      <section class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Recebido em</th>
              <th>Origem</th>
              <th>Hostname</th>
              <th>IP</th>
              <th>Sistema</th>
              <th>Status</th>
              <th>Coleta</th>
              <th>Qtd.</th>
              <th>Discos nao utilizados</th>
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
        if self.path == "/":
            self.respond_html(HTTPStatus.OK, render_table(load_records()))
            return

        if self.path == "/health":
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


def main() -> None:
    ensure_parent_dir(OUTPUT_FILE)
    server = ThreadingHTTPServer((HOST, PORT), CollectorHandler)
    LOGGER.info("Starting collector on %s:%s path=%s", HOST, PORT, POST_PATH)
    server.serve_forever()


if __name__ == "__main__":
    main()
