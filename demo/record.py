"""Record the Sachet demo: one browser session against the locally running app.

Start the app first (live mode):  sachet serve --port 8000
Then:  python demo/record.py         (writes demo/out/raw.webm and demo/out/segments.json)
Optional: --base http://127.0.0.1:8000
"""
import argparse
import html
import json
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SLIDES = HERE / "slides"
OUT = HERE / "out"
DUR = json.loads((HERE / "audio" / "durations.json").read_text())
CHROME = "/usr/bin/google-chrome"
VENV = REPO / ".venv" / "bin"

CURSOR_JS = """
document.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;' +
    'background:rgba(255,196,0,.55);border:2px solid rgba(40,40,40,.8);pointer-events:none;' +
    'transform:translate(-50%,-50%);left:640px;top:400px';
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
});
"""


def terminal_slide(name, title, commands, caption=""):
    """Run real commands and render their real output as a terminal page."""
    parts = []
    for cmd, show in commands:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=REPO, timeout=180)
        out = (res.stdout + res.stderr).strip()
        parts.append(f'<span class="p">$</span> <span class="c">{html.escape(show)}</span>\n'
                     f'{html.escape(out)}\n\n')
    page = (f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css">'
            f'</head><body><div class="wrap"><div class="caption">{html.escape(caption)}</div>'
            f'<div class="term"><div class="bar">{html.escape(title)}</div><pre>{"".join(parts)}</pre>'
            f'</div></div></body></html>')
    path = SLIDES / f"{name}.html"
    path.write_text(page)
    return path.as_uri()


class Rec:
    def __init__(self, page):
        self.page = page
        self.t0 = time.monotonic()
        self.segs = []
        self.cur = None

    def seg(self, name):
        self.end()
        self.cur = (name, time.monotonic())
        print(f"[{time.monotonic() - self.t0:6.1f}] {name}", flush=True)

    def end(self, pad=0.8):
        if not self.cur:
            return
        name, start = self.cur
        need = DUR[name] + pad
        elapsed = time.monotonic() - start
        if elapsed < need:
            self.page.wait_for_timeout(int((need - elapsed) * 1000))
        self.segs.append({"name": name, "start": start - self.t0, "end": time.monotonic() - self.t0})
        self.cur = None

    def move(self, loc):
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=16)
        self.page.wait_for_timeout(150)

    def click(self, loc, wait=600):
        self.move(loc)
        loc.click()
        self.page.wait_for_timeout(wait)

    def scroll_to(self, selector, wait=700):
        self.page.locator(selector).first.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'start'})")
        self.page.wait_for_timeout(wait)

    def wait_report(self, timeout=90000):
        self.page.wait_for_function(
            "() => { const v = document.getElementById('verdict'); return v && /Risk score/.test(v.innerText); }",
            timeout=timeout)
        self.page.wait_for_timeout(500)


def run_example(r, label):
    pg = r.page
    pg.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    pg.wait_for_timeout(400)
    r.click(pg.get_by_role("button", name=label))
    r.click(pg.get_by_role("button", name="Investigate offer"), 300)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.webm"):
        f.unlink()
    n_tests = subprocess.run(f"{VENV}/pytest --collect-only -q | tail -1", shell=True, cwd=REPO,
                             capture_output=True, text=True).stdout.split()[0]
    (SLIDES / "close_final.html").write_text((SLIDES / "close.html").read_text().replace("__TESTS__", n_tests))
    term = terminal_slide("terminal", "sachet: command line, tests and MCP", [
        (f"{VENV}/sachet check examples/impersonation_offer.txt 2>/dev/null | head -14",
         "sachet check examples/impersonation_offer.txt"),
        (f"{VENV}/pytest -q 2>&1 | tail -1", "pytest -q"),
        (f"{VENV}/python -c \"import asyncio; from sachet.mcp_server import build_server; "
         f"print([t.name for t in asyncio.run(build_server().list_tools())])\"",
         "python -c 'list MCP tools'"),
    ], "Same agent, same cached SerpApi results: CLI, offline tests, MCP tool")

    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME)
        ctx = br.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(OUT),
                             record_video_size={"width": 1280, "height": 800}, locale="en-US",
                             timezone_id="Asia/Kolkata")
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        r = Rec(page)

        r.seg("s00_title")
        page.goto((SLIDES / "title.html").as_uri())
        page.wait_for_timeout(500)

        r.seg("s01_paste")
        page.goto(args.base)
        page.wait_for_load_state("networkidle")
        r.click(page.get_by_role("button", name="impersonation offer"), 1200)
        r.move(page.locator("textarea").first)
        page.wait_for_timeout(2500)
        r.click(page.get_by_role("button", name="Investigate offer"), 200)

        r.seg("s02_timeline")
        r.move(page.locator("#timeline").first)
        r.wait_report()

        r.seg("s03_verdict")
        r.scroll_to("#verdict", 1500)
        page.mouse.wheel(0, 350)
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 350)

        r.seg("s04_genuine")
        run_example(r, "genuine internship")
        r.wait_report()
        r.scroll_to("#verdict", 1500)
        page.mouse.wheel(0, 300)

        r.seg("s05_task")
        run_example(r, "fake task job")
        r.wait_report()
        r.scroll_to("#verdict", 1500)
        page.wait_for_timeout(3500)
        r.scroll_to("#next", 800)

        r.seg("s06_terminal")
        page.goto(term)
        page.wait_for_timeout(500)

        r.seg("s07_close")
        page.goto((SLIDES / "close_final.html").as_uri())
        r.end()

        video = page.video.path()
        ctx.close()
        br.close()
    Path(video).rename(OUT / "raw.webm")
    (OUT / "segments.json").write_text(json.dumps({"segments": r.segs}, indent=1))
    print("recorded", OUT / "raw.webm", round(r.segs[-1]["end"], 1), "s")


if __name__ == "__main__":
    main()
