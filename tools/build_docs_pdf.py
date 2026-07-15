"""Build frontend/LitGraph-Documentation.pdf from frontend/docs.html.

Rendered by headless Chromium (Playwright) so the PDF is exactly what the page says
and the SERVER never needs a PDF engine -- LitGraph's runtime stays on its two
dependencies (requests, pypdf). Playwright is a dev-only tool, not a runtime dep.

The print stylesheet in docs.html strips the nav/header and forces BOTH the plain
and technical blocks to show, so the PDF is always the complete document regardless
of the voice switch.

Usage:
    pip install playwright && playwright install chromium
    python tools/build_docs_pdf.py            # boots its own throwaway server
    python tools/build_docs_pdf.py --url http://localhost:8000/docs

Re-run this after editing docs.html, or the PDF silently goes stale.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "backend")
OUT = os.path.join(ROOT, "frontend", "LitGraph-Documentation.pdf")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url, proc, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        if proc and proc.poll() is not None:
            raise RuntimeError(f"server exited early (code {proc.returncode})")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise RuntimeError(f"server did not come up at {url}")


def build(url: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is required to build the PDF:\n"
                 "    pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(url, wait_until="networkidle")
        # The version is fetched from /api/config; let it land before we snapshot.
        pg.wait_for_timeout(900)

        version = pg.evaluate("document.getElementById('vline')?.textContent || '?'")
        pg.emulate_media(media="print")
        pg.pdf(
            path=OUT,
            format="A4",
            print_background=True,
            margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
            display_header_footer=True,
            header_template='<div style="font-size:7pt;color:#888;width:100%;padding:0 14mm;">'
                            '<span style="float:left">LitGraph — Documentation</span>'
                            f'<span style="float:right">v{version}</span></div>',
            footer_template='<div style="font-size:7pt;color:#888;width:100%;padding:0 14mm;">'
                            '<span style="float:left">Created by Shreyan Kundu</span>'
                            '<span style="float:right">Page <span class="pageNumber"></span>'
                            ' of <span class="totalPages"></span></span></div>',
        )
        b.close()

    if errs:
        print("  ! page reported JS errors:", "; ".join(errs[:3]))
    size = os.path.getsize(OUT)
    print(f"  wrote {OUT}")
    print(f"  version v{version} · {size/1024:.0f} KB")
    if size < 20_000:
        sys.exit("PDF looks suspiciously small - check docs.html rendered correctly.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Render this URL instead of booting a throwaway server.")
    args = ap.parse_args()

    if args.url:
        build(args.url)
        return

    port = _free_port()
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=BACKEND, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _wait(f"http://127.0.0.1:{port}/health", proc)
        build(f"http://127.0.0.1:{port}/docs")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
