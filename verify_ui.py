"""Visual + geometric verification of the RTL layout and project bubbles.

Launches the real Streamlit app, logs in with a temporary admin, and uses a
real browser to check computed styles / element geometry, saving screenshots.

Run with:  python verify_ui.py
"""

import os
import subprocess
import sys
import time

import requests
from playwright.sync_api import sync_playwright

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin

PORT = 8601
BASE = f"http://localhost:{PORT}"
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shots")
TEMP_PROJECTS = ["בדיקה: בוט AI", "בדיקה: המרת מסמכים", "בדיקה: לוח בקרה"]


def seed():
    create_temp_admin()
    for name in TEMP_PROJECTS:
        db.add_project(name, TEMP_ADMIN)


def unseed():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = ANY(%s)", (TEMP_PROJECTS,))
        ids = [r["id"] for r in cur.fetchall()]
    for pid in ids:
        db.delete_project(pid)
    cleanup()


def start_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "main.py",
         "--server.headless", "true", "--server.port", str(PORT),
         "--browser.gatherUsageStats", "false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            if requests.get(f"{BASE}/_stcore/health", timeout=2).status_code == 200:
                return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("Streamlit server did not start")


def main():
    os.makedirs(SHOTS, exist_ok=True)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE, wait_until="networkidle")

        # --- Login screen ---------------------------------------------------
        page.get_by_placeholder("Username").fill(TEMP_ADMIN)
        page.get_by_placeholder("Password").fill(TEMP_ADMIN_PW)
        page.screenshot(path=os.path.join(SHOTS, "1_login.png"))
        page.get_by_role("button", name="כניסה").click()

        page.wait_for_selector("text=ברוך הבא", timeout=30000)
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(SHOTS, "2_welcome_rtl.png"), full_page=True)

        # --- RTL checks ------------------------------------------------------
        direction = page.evaluate(
            "getComputedStyle(document.querySelector('[data-testid=\"stMain\"]')).direction"
        )
        results.append(("main container direction is rtl", direction == "rtl", direction))

        sidebar = page.locator('[data-testid="stSidebar"]').bounding_box()
        main = page.locator('[data-testid="stMain"]').bounding_box()
        sidebar_right = sidebar["x"] > main["x"]
        results.append(
            ("sidebar is on the RIGHT side",
             sidebar_right, f"sidebar x={sidebar['x']:.0f}, main x={main['x']:.0f}"),
        )

        greeting = page.locator("text=ברוך הבא").first.inner_text()
        results.append((f"personalized greeting: '{greeting}'", TEMP_ADMIN in greeting, greeting))

        # --- Bubble checks ----------------------------------------------------
        bubbles = page.locator('.st-key-project_bubbles button')
        count = bubbles.count()
        results.append((f"project bubbles rendered ({count})", count >= len(TEMP_PROJECTS), count))

        style = page.evaluate(
            """() => {
                const b = document.querySelector('.st-key-project_bubbles button');
                const s = getComputedStyle(b);
                return {radius: s.borderTopLeftRadius, shadow: s.boxShadow,
                        align: s.textAlign, minH: s.minHeight};
            }"""
        )
        results.append(("bubbles are rounded", style["radius"].startswith("20"), style["radius"]))
        results.append(("bubbles have a soft shadow", "rgba" in style["shadow"], style["shadow"][:40]))
        results.append(("bubble text is right-aligned", style["align"] == "right", style["align"]))

        # Always drive one of OUR temp projects, never a real one — this test
        # writes a task and a chat message, and must not touch production data.
        first = page.locator(
            f'.st-key-project_bubbles button:has-text("{TEMP_PROJECTS[0]}")'
        ).first
        first.hover()
        page.wait_for_timeout(400)
        # Measure the element actually being hovered (not just the first bubble).
        transform = first.evaluate("el => getComputedStyle(el).transform")
        results.append(("hover lifts the bubble", transform not in ("none", ""), transform))
        page.screenshot(path=os.path.join(SHOTS, "3_bubble_hover.png"))

        # --- Navigation via bubble ---------------------------------------------
        label = first.inner_text().split("\n")[0]
        first.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=os.path.join(SHOTS, "4_project_dashboard_rtl.png"), full_page=True)
        heading = page.locator("h1").first.inner_text()
        results.append(
            (f"bubble click opened project '{heading.strip()}'",
             any(w in heading for w in label.split() if len(w) > 2), heading),
        )
        tabs_ok = page.locator('[data-baseweb="tab-list"]').count() > 0
        results.append(("project dashboard tabs render", tabs_ok, tabs_ok))

        # --- Tasks tab (RTL columns) ---------------------------------------------
        page.get_by_role("tab", name="Development Tasks").click()
        page.wait_for_timeout(1200)
        task_title = "בדיקת משימה RTL"
        page.get_by_placeholder("New task...").fill(task_title)
        page.locator('[data-testid="stMain"]').get_by_role(
            "button", name="➕ Add", exact=True
        ).click()
        page.wait_for_timeout(1200)  # optimistic echo should appear immediately
        echo_visible = page.get_by_text(task_title).count() > 0
        results.append(("optimistic task echo visible in RTL layout", echo_visible, echo_visible))

        # Bidi sanity: an English caption must not have its digits/words reordered.
        caption = page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('[data-testid="stMain"] p, [data-testid="stMain"] span')]
                    .find(e => /open \\/ /.test(e.textContent) && e.children.length === 0);
                if (!el) return null;
                return {text: el.textContent.trim(), bidi: getComputedStyle(el).unicodeBidi};
            }"""
        )
        if caption:
            results.append(
                (f"english caption keeps LTR word order: '{caption['text']}'",
                 caption["bidi"] == "plaintext", caption["bidi"]),
            )
        page.screenshot(path=os.path.join(SHOTS, "5_tasks_rtl.png"), full_page=True)

        # --- Chat tab (avatar side + optimistic echo) -----------------------------
        page.get_by_role("tab", name="Project Communication").click()
        page.wait_for_timeout(1200)
        page.get_by_placeholder("Message the team...").fill("שלום צוות — בדיקת RTL")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        chat_visible = page.get_by_text("שלום צוות — בדיקת RTL").count() > 0
        results.append(("optimistic chat echo visible in RTL layout", chat_visible, chat_visible))

        geom = page.evaluate(
            """() => {
                const msg = document.querySelector('[data-testid="stChatMessage"]');
                if (!msg) return null;
                const av = msg.querySelector('[data-testid="stChatMessageAvatar"]');
                const body = msg.querySelector('[data-testid="stChatMessageContent"]');
                if (!av || !body) return null;
                return {avatar: av.getBoundingClientRect().x,
                        body: body.getBoundingClientRect().x};
            }"""
        )
        if geom:
            results.append(
                ("chat avatar sits to the RIGHT of the message",
                 geom["avatar"] > geom["body"],
                 f"avatar x={geom['avatar']:.0f}, body x={geom['body']:.0f}"),
            )
        page.screenshot(path=os.path.join(SHOTS, "6_chat_rtl.png"), full_page=True)

        browser.close()

    print()
    ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}: {name}  [{detail}]")
        ok &= bool(passed)
    print("\n" + ("ALL UI CHECKS PASSED" if ok else "SOME UI CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    seed()
    server = start_server()
    try:
        code = main()
    finally:
        server.kill()
        unseed()
    sys.exit(code)
