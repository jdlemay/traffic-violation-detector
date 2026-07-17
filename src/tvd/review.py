"""Local review UI (Phase 7): browse recorded events, watch clips, export.

A deliberately small FastAPI app — one file, no build step, served on the
device (or your laptop against a copied data/ directory). It is LOCAL-ONLY by
default (binds 127.0.0.1); exposing it beyond localhost is a deliberate choice
with the privacy implications in docs/06.

Run:
    pip install fastapi uvicorn
    python -m tvd.review --db data/events.db --host 127.0.0.1 --port 8080
"""
from __future__ import annotations

import argparse
import html
import os
import sqlite3
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover - env dependent
    raise SystemExit(
        "The review UI needs FastAPI: pip install fastapi uvicorn") from exc


def _rows(db_path: str, limit: int = 200) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_app(db_path: str) -> "FastAPI":
    app = FastAPI(title="TVDS Review", docs_url=None, redoc_url=None)
    media_roots: set[Path] = set()

    def _register_root(p: str | None):
        if p:
            media_roots.add(Path(p).resolve().parent)

    @app.get("/api/events")
    def api_events(limit: int = 200):
        return JSONResponse(_rows(db_path, limit))

    @app.get("/media")
    def media(path: str):
        # Only serve files that live under a directory some event row points
        # at — prevents the endpoint being used to read arbitrary files.
        target = Path(path).resolve()
        for r in _rows(db_path, 500):
            _register_root(r.get("clip_path"))
            _register_root(r.get("still_path"))
        if not any(root in target.parents or root == target.parent
                   for root in media_roots):
            raise HTTPException(403, "path not under a known media directory")
        if not target.exists():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    @app.get("/", response_class=HTMLResponse)
    def index():
        cards = []
        for r in _rows(db_path):
            when = html.escape(str(r.get("ts_utc", "")))
            typ = html.escape(str(r.get("type", "")))
            conf = r.get("confidence") or 0
            speed = r.get("speed_mps")
            lat, lon = r.get("lat"), r.get("lon")
            gps = (f'<a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}'
                   f'#map=17/{lat}/{lon}" target="_blank">{lat:.5f}, {lon:.5f}</a>'
                   if lat is not None and lon is not None else "—")
            clip = r.get("clip_path")
            still = r.get("still_path")
            media_html = ""
            if clip:
                media_html += (f'<video controls preload="none" '
                               f'src="/media?path={html.escape(clip)}"></video>')
            elif still:
                media_html += (f'<img loading="lazy" '
                               f'src="/media?path={html.escape(still)}">')
            badge = "degraded" if r.get("degraded") else f"tier {r.get('tier')}"
            cards.append(f"""
            <div class="card">
              <div class="head"><span class="type">{typ}</span>
                <span class="badge">{badge}</span>
                <span class="conf">conf {conf:.2f}</span></div>
              <div class="meta">{when} · {gps} ·
                {f"{speed*2.23694:.0f} mph" if speed is not None else "speed —"}</div>
              {media_html}
              <details><summary>details</summary>
                <pre>{html.escape(str(r.get("meta_json", "")))}</pre>
                <div class="hash">sha256: {html.escape(str(r.get("clip_sha256") or "—"))}</div>
              </details>
            </div>""")
        body = "\n".join(cards) or "<p>No events recorded yet.</p>"
        return f"""<!doctype html><html><head><meta charset="utf-8">
<title>TVDS Review</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body {{ font: 15px/1.45 system-ui, sans-serif; margin: 0; background: #111;
        color: #eee; }}
 header {{ padding: 14px 20px; background: #1b1b1b; position: sticky; top: 0;
          border-bottom: 1px solid #333; }}
 h1 {{ font-size: 17px; margin: 0; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
         gap: 14px; padding: 16px 20px; }}
 .card {{ background: #1d1d1f; border: 1px solid #333; border-radius: 10px;
         padding: 12px 14px; }}
 .head {{ display: flex; gap: 8px; align-items: baseline; }}
 .type {{ font-weight: 600; }}
 .badge {{ font-size: 12px; color: #f90; }}
 .conf {{ margin-left: auto; font-size: 12px; color: #9a9; }}
 .meta {{ font-size: 12.5px; color: #aaa; margin: 4px 0 8px; }}
 video, img {{ width: 100%; border-radius: 6px; background: #000; }}
 details {{ margin-top: 8px; font-size: 12.5px; color: #bbb; }}
 pre {{ white-space: pre-wrap; }}
 .hash {{ font-size: 11px; color: #777; word-break: break-all; }}
 a {{ color: #7ab8ff; }}
</style></head><body>
<header><h1>TVDS · recorded events</h1></header>
<div class="grid">{body}</div>
</body></html>"""

    return app


def main(argv=None):
    p = argparse.ArgumentParser(description="TVDS event review UI")
    p.add_argument("--db", default="data/events.db")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args(argv)
    if not os.path.exists(args.db):
        raise SystemExit(f"database not found: {args.db}")
    import uvicorn
    uvicorn.run(create_app(args.db), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
