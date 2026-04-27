import base64
import http.server
import html
import json
import re
import socketserver
import subprocess
import threading
import zlib
from pathlib import Path

import httpx

from src.utils.config import config
from src.utils.logger import log


VIEWER_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Audio &rarr; Mermaid</title>
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: #fafafa; font-family: system-ui, sans-serif; }
  #app { display: flex; height: 100vh; }
  #diagram { flex: 1; position: relative; overflow: hidden; min-width: 0; }
  #root { width: 100%; height: 100%; position: relative; overflow: hidden; }
  #root > svg { width: 100%; height: 100%; display: block; cursor: grab; }
  #root > svg:active { cursor: grabbing; }
  #root g.node, #root g.cluster { cursor: pointer; }
  #placeholder { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); color: #888; font-size: 14px; }
  #hud { position: fixed; bottom: 8px; left: 50%; transform: translateX(-50%);
         background: rgba(0,0,0,0.55); color: #fff; font-size: 11px;
         padding: 4px 12px; border-radius: 4px; pointer-events: none;
         font-family: ui-monospace, SFMono-Regular, Menlo, monospace; z-index: 10; }
  #annotations { width: 340px; flex-shrink: 0; background: #fff;
                 border-left: 1px solid #e5e5e5; padding: 16px 18px 24px;
                 overflow-y: auto; box-sizing: border-box; }
  #annotations.hidden { display: none; }
  #annotations h2 { font-size: 13px; font-weight: 600; color: #333; margin: 0 0 12px; }
  #annotations h3 { font-size: 10.5px; font-weight: 600; text-transform: uppercase;
                    color: #888; letter-spacing: 0.06em; margin: 16px 0 4px;
                    padding-top: 12px; border-top: 1px solid #f0f0f0; }
  #annotations h3:first-of-type { padding-top: 0; border-top: none; }
  #annotations .body { font-size: 12.5px; line-height: 1.5; color: #222;
                       white-space: pre-wrap; word-break: break-word;
                       font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  #annotations .empty { color: #aaa; font-size: 12px; font-style: italic; }
</style>
<script src="https://cdn.jsdelivr.net/npm/panzoom@9.4.3/dist/panzoom.min.js"></script>
</head>
<body>
<div id="app">
  <div id="diagram">
    <div id="root"><div id="placeholder">Waiting for first diagram&hellip;</div></div>
    <div id="hud">click: zoom node &middot; scroll: zoom &middot; drag: pan &middot; R: reset &middot; F: fit &middot; H: toggle panel</div>
  </div>
  <aside id="annotations"><span class="empty">No annotations yet.</span></aside>
</div>
<script>
  const root = document.getElementById('root');
  const annotations = document.getElementById('annotations');
  let lastSvg = '';
  let lastAnn = '';
  let pz = null;
  let currentSvg = null;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function fitToContent() {
    if (!currentSvg) return;
    let bbox;
    try { bbox = currentSvg.getBBox(); } catch (_) { return; }
    if (!bbox.width || !bbox.height) {
      // SVG not laid out yet; retry on next frame
      requestAnimationFrame(fitToContent);
      return;
    }
    const pad = Math.max(bbox.width, bbox.height) * 0.02;
    currentSvg.setAttribute('viewBox',
      `${bbox.x - pad} ${bbox.y - pad} ${bbox.width + pad * 2} ${bbox.height + pad * 2}`);
    if (pz) {
      const t = pz.getTransform();
      pz.moveBy(-t.x, -t.y, false);
      pz.zoomAbs(0, 0, 1);
    }
  }

  function zoomToNode(node) {
    if (!pz || !node) return;
    const nodeRect = node.getBoundingClientRect();
    const cont = root.getBoundingClientRect();
    if (!nodeRect.width || !nodeRect.height) return;
    // Target: node fills ~50% of the smaller container dimension.
    const t = pz.getTransform();
    const targetScale = Math.min(
      (cont.width  * 0.5) / nodeRect.width  * t.scale,
      (cont.height * 0.5) / nodeRect.height * t.scale,
      8
    );
    const nodeCx = nodeRect.left + nodeRect.width / 2;
    const nodeCy = nodeRect.top  + nodeRect.height / 2;
    const targetCx = cont.left + cont.width / 2;
    const targetCy = cont.top  + cont.height / 2;
    // zoomAbs anchors at (nodeCx, nodeCy) so the node center stays put on screen,
    // then translate so the node center moves to container center.
    pz.zoomAbs(nodeCx, nodeCy, targetScale);
    const post = pz.getTransform();
    const dx = targetCx - nodeCx;
    const dy = targetCy - nodeCy;
    if (pz.smoothMoveTo) {
      pz.smoothMoveTo(post.x + dx, post.y + dy);
    } else {
      pz.moveBy(dx, dy, true);
    }
  }

  function mountSvg(text) {
    if (pz) { pz.dispose(); pz = null; }
    root.innerHTML = text;
    const svg = root.querySelector('svg');
    currentSvg = svg;
    if (!svg) return;
    svg.removeAttribute('width');
    svg.removeAttribute('height');
    svg.style.width = '100%';
    svg.style.height = '100%';
    svg.style.maxWidth = 'none';
    svg.style.maxHeight = 'none';
    fitToContent();
    if (window.panzoom) {
      pz = panzoom(svg, { maxZoom: 20, minZoom: 0.1, zoomDoubleClickSpeed: 1, smoothScroll: false });
    }
    // Click to zoom: a real click (not a pan) on a node centers + zooms it;
    // clicking empty diagram area fits the whole diagram.
    svg.addEventListener('click', (e) => {
      const node = e.target.closest('g.node, g.cluster');
      if (node) {
        zoomToNode(node);
      } else {
        fitToContent();
      }
    });
  }

  function renderAnnotations(items) {
    if (!items || !items.length) {
      annotations.innerHTML = '<span class="empty">No annotations yet.</span>';
      return;
    }
    const parts = ['<h2>Spec</h2>'];
    for (const item of items) {
      parts.push('<h3>' + escapeHtml(item.title) + '</h3>');
      parts.push('<div class="body">' + escapeHtml(item.body || '') + '</div>');
    }
    annotations.innerHTML = parts.join('');
  }

  async function tick() {
    try {
      const res = await fetch('diagram.svg?t=' + Date.now(), { cache: 'no-store' });
      if (res.ok) {
        const text = await res.text();
        if (text && text !== lastSvg) {
          lastSvg = text;
          mountSvg(text);
        }
      }
    } catch (_) {}
    try {
      const res = await fetch('annotations.json?t=' + Date.now(), { cache: 'no-store' });
      if (res.ok) {
        const text = await res.text();
        if (text !== lastAnn) {
          lastAnn = text;
          renderAnnotations(JSON.parse(text));
        }
      }
    } catch (_) {}
  }
  setInterval(tick, 1000);
  tick();

  document.addEventListener('keydown', e => {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    const k = e.key.toLowerCase();
    if (k === 'r') {
      if (!pz) return;
      const t = pz.getTransform();
      pz.moveBy(-t.x, -t.y, false);
      pz.zoomAbs(0, 0, 1);
    } else if (k === 'f') {
      fitToContent();
    } else if (k === 'h') {
      annotations.classList.toggle('hidden');
      // Re-fit after layout change so the diagram reclaims the room.
      requestAnimationFrame(fitToContent);
    }
  });
</script>
</body>
</html>
"""


_ANNOTATION_TITLE_RE = re.compile(r"^([A-Z][A-Z0-9 &/()\-]{2,}):\s*(.*)$")


def _extract_annotations(mermaid_code: str) -> list[dict]:
    """Parse `%% TITLE: body` annotation blocks from the Mermaid source.

    Supports both single-line (`%% TITLE: body`) and continuation form:
        %% TITLE:
        %% - bullet 1
        %% - bullet 2
    """
    out: list[dict] = []
    current: dict | None = None
    for raw in mermaid_code.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("%%"):
            current = None
            continue
        content = stripped[2:].strip()
        if not content:
            current = None
            continue
        m = _ANNOTATION_TITLE_RE.match(content)
        if m:
            title = m.group(1).strip().rstrip(":").strip()
            body = m.group(2).strip()
            current = {"title": title, "body": body}
            out.append(current)
        elif current is not None:
            current["body"] = (current["body"] + "\n" + content).strip()
    return out


def _error_svg(title: str, detail: str) -> bytes:
    safe_title = html.escape(title)
    safe_detail = html.escape(detail)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="500" '
        f'viewBox="0 0 900 500">'
        f'<foreignObject x="0" y="0" width="900" height="500">'
        f'<div xmlns="http://www.w3.org/1999/xhtml" '
        f'style="font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;'
        f'padding:24px;color:#333;background:#fff5f5;border:1px solid #fcc;'
        f'border-radius:8px;height:100%;box-sizing:border-box;'
        f'white-space:pre-wrap;word-break:break-word;overflow:auto;">'
        f'<div style="color:#c33;font-weight:600;margin-bottom:12px;">'
        f'{safe_title}</div>{safe_detail}</div>'
        f'</foreignObject></svg>'
    ).encode("utf-8")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class MermaidViewer:
    def __init__(self):
        self.dir: Path = Path(config.viewer_dir).expanduser()
        self.svg_path = self.dir / "diagram.svg"
        self.annotations_path = self.dir / "annotations.json"
        self.html_path = self.dir / "viewer.html"
        self.url = f"http://127.0.0.1:{config.viewer_port}/viewer.html"
        self._httpd: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    async def start(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.html_path.write_text(VIEWER_HTML)
        # Clear any stale SVG / annotations from a previous run so the viewer
        # shows the "Waiting…" placeholder instead of stale (possibly error) state.
        self.svg_path.unlink(missing_ok=True)
        self.annotations_path.unlink(missing_ok=True)

        directory = str(self.dir)

        def handler_factory(*args, **kwargs):
            return _QuietHandler(*args, directory=directory, **kwargs)

        try:
            self._httpd = socketserver.TCPServer(
                ("127.0.0.1", config.viewer_port), handler_factory
            )
        except OSError as e:
            log.error(
                f"Could not bind viewer server on port {config.viewer_port}: {e}. "
                "Set VIEWER_PORT to a free port."
            )
            raise

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info(f"Viewer serving at {self.url}")

        try:
            subprocess.Popen(["open", "-a", "Brave Browser", self.url])
        except Exception as e:
            log.warning(f"Could not open viewer in Brave ({e}); navigate manually to {self.url}")

    async def render(self, mermaid_code: str):
        backend = config.render_backend
        try:
            if backend == "mermaid_ink":
                svg = await self._render_mermaid_ink(mermaid_code)
            elif backend == "kroki":
                svg = await self._render_kroki(mermaid_code)
            else:
                raise ValueError(f"Unknown RENDER_BACKEND: {backend}")
        except httpx.HTTPStatusError as e:
            body = e.response.text[:400]
            log.error(f"{backend} rejected diagram ({e.response.status_code}): {body}")
            self._write(_error_svg(
                f"{backend} returned HTTP {e.response.status_code}",
                f"{body}\n\n--- mermaid source ---\n{mermaid_code}",
            ))
            return
        except Exception as e:
            log.error(f"{backend} render failed: {e}")
            self._write(_error_svg(
                f"{backend} render failed",
                f"{type(e).__name__}: {e}\n\n--- mermaid source ---\n{mermaid_code}",
            ))
            return

        self._write(svg)
        self._write_annotations(_extract_annotations(mermaid_code))
        log.info(f"Rendered diagram ({len(svg)} bytes) via {backend}")

    async def _render_mermaid_ink(self, mermaid_code: str) -> bytes:
        # mermaid.ink's `pako:` prefix accepts a JSON-wrapped payload
        # (same shape mermaid.live uses), zlib-deflated, base64url-encoded.
        # This shrinks the URL ~10x vs raw base64 — essential to stay under
        # nginx's URI length limit (raw base64 414s on diagrams >~3KB).
        payload = json.dumps({"code": mermaid_code, "mermaid": {"theme": "default"}})
        deflated = zlib.compress(payload.encode("utf-8"), 9)
        encoded = base64.urlsafe_b64encode(deflated).decode("ascii").rstrip("=")
        url = f"{config.render_url.rstrip('/')}/pako:{encoded}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            res = await client.get(url)
            res.raise_for_status()
            return res.content

    async def _render_kroki(self, mermaid_code: str) -> bytes:
        url = f"{config.render_url.rstrip('/')}/mermaid/svg"
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                url,
                content=mermaid_code.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
            res.raise_for_status()
            return res.content

    def _write(self, svg: bytes):
        tmp = self.svg_path.with_suffix(".svg.tmp")
        tmp.write_bytes(svg)
        tmp.replace(self.svg_path)

    def _write_annotations(self, items: list[dict]):
        tmp = self.annotations_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False))
        tmp.replace(self.annotations_path)

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
