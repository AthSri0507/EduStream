"""Step-0 prototype 3 driver (ARCHITECTURE §12 item 13): does a slow LLM call survive Streamlit re-runs?

Starts bench/proto_streamlit_app.py on port 8502 with the project venv, drives it with Playwright
(installed Chrome) and reports, for each scenario, whether the answer arrived:
  A threaded call, another widget clicked mid-call
  B inline call,   another widget clicked mid-call
  C inline call,   no interaction (only the 2 s auto-refresh fragment)
and whether the threaded answer was visible while streaming.

    <playwright python> bench\\proto_streamlit_check.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
URL = "http://localhost:8502"


def wait_text(page, text, timeout_s):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if text in page.content():
            return round(timeout_s - (deadline - time.time()), 1)
        time.sleep(0.2)
    return None


def main() -> None:
    server = subprocess.Popen([str(VENV_PY), "-m", "streamlit", "run", str(ROOT / "bench" / "proto_streamlit_app.py"),
                               "--server.headless", "true", "--server.port", "8502", "--server.address", "localhost"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_page()
            for _ in range(60):
                try:
                    page.goto(URL)
                    page.wait_for_selector("text=Ask (threaded)", timeout=2000)
                    break
                except Exception:  # noqa: BLE001 - server still starting
                    time.sleep(1)

            # A: threaded + interaction mid-call
            page.get_by_role("button", name="Ask (threaded)").click()
            time.sleep(1.5)
            partial = page.locator("text=THREADED-TEXT").first.inner_text() if "THREADED-TEXT" in page.content() else ""
            page.get_by_text("another widget").click()
            done = wait_text(page, "THREADED-DONE", 8)
            results["A_threaded_with_click"] = {"answer_arrived": done is not None,
                                                "partial_text_at_1.5s": partial.replace("THREADED-TEXT:", "").strip()}

            # B: inline + interaction mid-call
            page.reload()
            page.wait_for_selector("text=Ask (inline)")
            page.get_by_role("button", name="Ask (inline)").click()
            time.sleep(1.0)
            page.get_by_text("another widget").click()
            results["B_inline_with_click"] = {"answer_arrived": wait_text(page, "INLINE-DONE", 8) is not None}

            # C: inline, no interaction (only the auto-refreshing fragments)
            browser.close()
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_page()                      # new session: no stored answer
            page.goto(URL)
            page.wait_for_selector("text=Ask (inline)")
            page.get_by_role("button", name="Ask (inline)").click()
            results["C_inline_no_click"] = {"answer_arrived": wait_text(page, "INLINE-DONE", 8) is not None}
            browser.close()
    finally:
        server.terminate()
    out = ROOT / "bench" / "results" / "proto_streamlit.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    sys.exit(main())
