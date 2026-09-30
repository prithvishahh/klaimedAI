"""Record a captioned screen video of the Klaimed console (for the YC application).

Drives the REAL console at http://localhost:8800 with Playwright, overlays a
caption bar + a moving cursor, records the browser to webm, then ffmpeg-encodes
an mp4. Start the server first:  python -m demo.server

Usage:  python -m demo.record_demo   ->  ~/Desktop/klaimed-demo.mp4
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8800"
W, H = 1440, 900
OUT_DIR = Path("/private/tmp/klaimed-rec")
FINAL = Path.home() / "Desktop" / "klaimed-demo.mp4"

_INJECT = """
() => {
  const cap = document.createElement('div'); cap.id='__cap'; document.body.appendChild(cap);
  const cur = document.createElement('div'); cur.id='__cur'; document.body.appendChild(cur);
  window.__setCap = (t) => { cap.textContent = t || ''; cap.style.opacity = t ? '1' : '0'; };
  window.__moveCur = (x, y) => { cur.style.left = x+'px'; cur.style.top = y+'px'; };
}
"""

_CSS = """
#__cap { position: fixed; left: 50%; bottom: 36px; transform: translateX(-50%);
  background: #16160f; color: #f7f5ef; font-family: Inter, sans-serif; font-size: 18px;
  font-weight: 500; padding: 13px 26px; border-radius: 999px; z-index: 99998; opacity: 0;
  transition: opacity .45s ease; box-shadow: 0 14px 34px rgba(0,0,0,.32); max-width: 78%;
  text-align: center; }
#__cur { position: fixed; width: 20px; height: 20px; border-radius: 50%;
  background: rgba(12,107,79,.3); border: 2px solid #0c6b4f; z-index: 99999;
  transform: translate(-50%,-50%); left: 720px; top: 460px; pointer-events: none;
  transition: left .55s cubic-bezier(.4,0,.2,1), top .55s cubic-bezier(.4,0,.2,1);
  box-shadow: 0 0 0 6px rgba(12,107,79,.10); }
"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in glob.glob(str(OUT_DIR / "*.webm")):
        os.remove(old)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": W, "height": H},
            device_scale_factor=2,
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1200)  # let web fonts settle
        page.add_style_tag(content=_CSS)
        page.evaluate(_INJECT)

        def cap(text: str) -> None:
            page.evaluate("(t) => window.__setCap(t)", text)

        def point(selector: str) -> None:
            box = page.locator(selector).first.bounding_box()
            if box:
                page.evaluate("([x,y]) => window.__moveCur(x,y)",
                              [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])

        def click(selector: str) -> None:
            point(selector)
            page.wait_for_timeout(650)
            page.locator(selector).first.click()

        def scroll_top() -> None:
            page.evaluate("() => window.scrollTo({top:0, behavior:'smooth'})")

        # ---- beats ----
        cap("Klaimed — the AI billing department for medical practices")
        page.wait_for_timeout(2600)

        cap("A practice's denials arrive as a standard 835 remittance file")
        click("#loadSample")
        page.wait_for_timeout(2200)

        cap("Klaimed ranks the queue by dollars × recovery odds, and tracks deadlines")
        point(".kpis")
        page.wait_for_timeout(2600)

        cap("Open a denied claim")
        click('#queueBody tr[data-cn="PCN10002"]')
        page.wait_for_timeout(2200)

        cap("The exact fix — a data correction. Procedure codes are never touched.")
        page.wait_for_timeout(2800)

        cap("A guardrail blocks any code change in code, not a prompt — so it can't upcode")
        point(".pill--ok")
        page.wait_for_timeout(2800)

        cap("Out comes a standards-compliant 837P, ready to resubmit")
        click(".edi-toggle > summary")
        page.wait_for_timeout(2600)

        cap("One click works the entire fixable backlog")
        click("#workAll")
        page.wait_for_timeout(2400)

        cap("$610 recovered — the practice keeps the net, we're paid only on results")
        point("#kpiRecovered")
        page.wait_for_timeout(2800)

        cap("Medical-necessity denials get an appeal citing the payer's own policy")
        click('#queueBody tr[data-cn="PCN10004"]')
        page.wait_for_timeout(3000)

        cap("Every action is logged to an append-only audit trail")
        page.evaluate("() => window.scrollTo({top: document.body.scrollHeight, behavior:'smooth'})")
        page.wait_for_timeout(2600)

        scroll_top()
        cap("Klaimed — get back the money your practice wrote off")
        page.wait_for_timeout(2600)
        cap("")
        page.wait_for_timeout(600)

        ctx.close()
        browser.close()

    webms = sorted(glob.glob(str(OUT_DIR / "*.webm")), key=os.path.getmtime)
    if not webms:
        print("ERROR: no video captured", file=sys.stderr)
        return 1
    webm = webms[-1]
    print(f"raw video: {webm}")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", webm,
        "-vf", f"scale={W}:{H}:flags=lanczos", "-r", "30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-movflags", "+faststart", str(FINAL),
    ], check=True, capture_output=True)
    size_mb = FINAL.stat().st_size / 1e6
    print(f"wrote {FINAL} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
