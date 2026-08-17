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


WIDGET_TASK = "משימה דחופה לוידגט"


def seed():
    create_temp_admin()
    # Give the temp admin an address so the mailto: icon has a recipient.
    db.set_user_contact(TEMP_ADMIN, "temp-admin@example.test", None)
    pids = [db.add_project(name, TEMP_ADMIN) for name in TEMP_PROJECTS]
    # An open urgent task so the home-screen widget has something to show.
    # Seeded into the SECOND project: the browser flow drives the first one and
    # asserts on its task list, which must not contain extra rows.
    # add_project returns None on a duplicate name (leftover from an aborted
    # run) — never seed a task without a valid project id.
    assert pids[1] is not None, "temp project already exists — run unseed() first"
    db.add_task(WIDGET_TASK, TEMP_ADMIN, TEMP_ADMIN, pids[1], "project", is_urgent=True)


def unseed():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = ANY(%s)", (TEMP_PROJECTS,))
        ids = [r["id"] for r in cur.fetchall()]
        # Also remove seeded widget tasks that lost their project (aborted runs).
        cur.execute("DELETE FROM tasks WHERE title = %s", (WIDGET_TASK,))
    for pid in ids:
        db.delete_project(pid)
    cleanup()


def start_server():
    os.makedirs(SHOTS, exist_ok=True)
    log = open(os.path.join(SHOTS, "server.log"), "w", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "main.py",
         "--server.headless", "true", "--server.port", str(PORT),
         "--browser.gatherUsageStats", "false"],
        stdout=log, stderr=subprocess.STDOUT,
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
        page.get_by_placeholder("שם משתמש").fill(TEMP_ADMIN)
        page.get_by_placeholder("סיסמה").fill(TEMP_ADMIN_PW)
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

        # --- Urgent-tasks widget on the home screen ------------------------------
        widget_count = page.locator(".st-key-urgent_widget").count()
        results.append(("urgent-tasks widget rendered on home", widget_count > 0, widget_count))
        seeded = page.locator(f'.st-key-urgent_widget button:has-text("{WIDGET_TASK}")')
        results.append(("widget lists the seeded urgent task", seeded.count() > 0, seeded.count()))
        widget_style = page.evaluate(
            """() => { const el = document.querySelector('.st-key-urgent_widget');
                       if (!el) return null;
                       const s = getComputedStyle(el);
                       return {radius: parseFloat(s.borderTopLeftRadius),
                               shadow: s.boxShadow.slice(0, 40),
                               border: s.borderColor,
                               blur: (s.backdropFilter || '').includes('blur')}; }"""
        )
        results.append(
            ("widget is an Apple-style glass card (rounded, soft shadow, blur)",
             bool(widget_style) and widget_style["radius"] >= 16
             and "rgba" in widget_style["shadow"] and widget_style["blur"],
             widget_style),
        )

        # --- Emoji placement: the leading emoji must be the RIGHTMOST glyph -------
        emoji_geometry = page.evaluate(
            """() => {
                const p = document.querySelector('.st-key-nav_home button p');
                if (!p || !p.firstChild) return null;
                const range = document.createRange();
                range.setStart(p.firstChild, 0);
                range.setEnd(p.firstChild, 2);  // the emoji is a surrogate pair
                const emoji = range.getBoundingClientRect();
                const full = p.getBoundingClientRect();
                return {emojiRight: emoji.right, mid: (full.left + full.right) / 2,
                        dir: getComputedStyle(p).direction};
            }"""
        )
        results.append(
            ("nav emoji renders to the RIGHT of the Hebrew text",
             bool(emoji_geometry) and emoji_geometry["dir"] == "rtl"
             and emoji_geometry["emojiRight"] > emoji_geometry["mid"],
             emoji_geometry),
        )

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
        results.append(
            ("bubbles are rounded (>=16px)",
             float(style["radius"].replace("px", "")) >= 16, style["radius"]),
        )
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
        page.get_by_role("tab", name="משימות פיתוח").click()
        page.wait_for_timeout(1200)
        task_title = "בדיקת משימה RTL"
        page.get_by_placeholder("משימה חדשה...").fill(task_title)

        # Mark it urgent via the inline toggle (label click — the input is hidden).
        urgent_box = page.locator('[class*="st-key-task_urgent_"] label').first
        results.append(("urgent toggle present in the task bar", urgent_box.count() > 0, True))
        # Inline layout: the toggle must sit on the same row as the input + button.
        row_geometry = page.evaluate(
            """() => {
                // Scope to the task-creation form itself — the sidebar has a form too.
                const form = document.querySelector('[data-testid="stMain"] [data-testid="stForm"]');
                if (!form) return null;
                const input = form.querySelector('input[type="text"]');
                const chk = form.querySelector('[class*="st-key-task_urgent_"]');
                const btn = form.querySelector('[data-testid="stFormSubmitButton"] button');
                if (!input || !chk || !btn) return null;
                const y = e => e.getBoundingClientRect().y;
                const x = e => e.getBoundingClientRect().x;
                return {dy: Math.max(Math.abs(y(input) - y(chk)), Math.abs(y(chk) - y(btn))),
                        inputX: x(input), chkX: x(chk), btnX: x(btn)};
            }"""
        )
        results.append(
            ("urgent toggle is inline with input and Add button (RTL order)",
             bool(row_geometry) and row_geometry["dy"] < 45
             and row_geometry["inputX"] > row_geometry["chkX"] > row_geometry["btnX"],
             row_geometry),
        )
        urgent_box.click()
        page.wait_for_timeout(400)

        page.locator('[data-testid="stMain"]').get_by_role(
            "button", name="➕ הוספה", exact=True
        ).click()
        # Wait for the row to appear rather than sleeping a fixed amount — the
        # rerun now also dispatches a notification before re-rendering.
        try:
            page.wait_for_selector(f"text={task_title}", timeout=15000)
            echo_visible = True
        except Exception as exc:  # noqa: BLE001 — record as a failed check
            echo_visible = f"not rendered: {exc}"
        results.append(("optimistic task echo visible in RTL layout", echo_visible is True, echo_visible))

        # NOTE: the inline `.task-urgent` pill only exists while a task is still
        # an un-synced optimistic echo, so asserting on it here is inherently
        # racy — it is covered deterministically in test_urgent_tasks.py. What
        # matters in the browser is the interactive toggle, verified below.
        # Bidi sanity: a mixed Hebrew/number caption must not be reordered.
        caption = page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('[data-testid="stMain"] p, [data-testid="stMain"] span')]
                    .find(e => /\u05e4\u05ea\u05d5\u05d7\u05d5\u05ea/.test(e.textContent) && e.children.length === 0);
                if (!el) return null;
                return {text: el.textContent.trim(), bidi: getComputedStyle(el).unicodeBidi};
            }"""
        )
        if caption:
            results.append(
                (f"task counter caption renders: '{caption['text']}'",
                 caption["bidi"] == "plaintext", caption["bidi"]),
            )
        # --- Completion checkbox: strikethrough + dimming --------------------------
        # Let the optimistic write land, then force a server rerun so the echo is
        # replaced by the real DB row (which has the checkbox). NOTE: never call
        # page.reload() here — that starts a new Streamlit session and logs out.
        page.wait_for_timeout(3000)
        page.get_by_role("button", name="🔄 רענון").click()
        page.wait_for_timeout(2500)
        page.get_by_role("tab", name="משימות פיתוח").click()  # rerun resets to tab 1
        page.wait_for_timeout(1500)

        # --- Urgency toggle on an existing task -----------------------------------
        urgent_on = page.locator('[class*="st-key-task_urgent_on_"] button').first
        pill = urgent_on.evaluate(
            """el => { const s = getComputedStyle(el);
                       return {text: el.textContent.trim(), color: s.color,
                               background: s.backgroundColor, radius: s.borderTopLeftRadius}; }"""
        )
        results.append(
            ("existing urgent task shows an interactive red 🔥 דחוף toggle",
             "דחוף" in pill["text"] and pill["color"] == "rgb(192, 32, 47)"
             and pill["radius"] == "999px",
             pill),
        )
        urgent_on.click()  # turn urgency OFF
        page.wait_for_selector('[class*="st-key-task_urgent_off_"] button', timeout=15000)
        # Move the pointer away and let the CSS transition settle, otherwise we
        # measure hover/mid-animation values instead of the resting style.
        page.mouse.move(5, 5)
        page.wait_for_timeout(600)
        off_style = page.evaluate(
            """() => { const el = document.querySelector('[class*="st-key-task_urgent_off_"] button');
                       const s = getComputedStyle(el);
                       return {filter: s.filter, opacity: s.opacity, border: s.borderStyle}; }"""
        )
        results.append(
            ("toggling off shows a greyed-out 🔥 button",
             "grayscale(1)" in off_style["filter"] and float(off_style["opacity"]) < 1,
             off_style),
        )
        page.locator('[class*="st-key-task_urgent_off_"] button').first.click()  # back ON
        page.wait_for_selector('[class*="st-key-task_urgent_on_"] button', timeout=15000)
        results.append(("toggling back on restores the urgent state", True, "round-trip ok"))

        # --- Larger mail icon ------------------------------------------------------
        mail_size = page.evaluate(
            """() => { const a = document.querySelector('a.task-mail');
                       return a ? getComputedStyle(a).fontSize : null; }"""
        )
        results.append(
            ("mail icon is enlarged (>=1.5rem / 24px)",
             bool(mail_size) and float(mail_size.replace("px", "")) >= 24, mail_size),
        )

        # --- Completion: checkbox -> green הושלם pill ------------------------------
        # Streamlit visually hides the real <input> behind a styled label.
        page.locator('[class*="st-key-task_done_"] label').first.click()
        page.wait_for_selector('[class*="st-key-task_undone_"] button', timeout=15000)
        done_pill = page.evaluate(
            """() => { const el = document.querySelector('[class*="st-key-task_undone_"] button');
                       const s = getComputedStyle(el);
                       const box = el.getBoundingClientRect();
                       const body = document.querySelector('[data-testid="stMain"]').getBoundingClientRect();
                       return {text: el.textContent.trim(), color: s.color,
                               background: s.backgroundColor, radius: s.borderTopLeftRadius,
                               fromRight: body.right - box.right}; }"""
        )
        results.append(
            ("completed task shows a green ✅ הושלם pill on the right",
             "הושלם" in done_pill["text"] and done_pill["color"] == "rgb(19, 122, 63)"
             and done_pill["fromRight"] < 120,
             done_pill),
        )
        checkbox_gone = page.locator('[class*="st-key-task_done_"] input').count() == 0
        results.append(("the checkbox is replaced once completed", checkbox_gone, checkbox_gone))
        done_style = page.evaluate(
            """() => {
                const el = document.querySelector('.task-done');
                if (!el) return null;
                const s = getComputedStyle(el);
                return {opacity: s.opacity, struck: !!el.querySelector('s'),
                        text: el.textContent.trim()};
            }"""
        )
        results.append(
            ("completed task is struck through and dimmed",
             bool(done_style) and done_style["struck"] and float(done_style["opacity"]) < 1,
             done_style),
        )
        # --- Manual mailto: icon --------------------------------------------------
        mail = page.evaluate(
            """() => {
                const a = document.querySelector('a.task-mail');
                if (!a) return null;
                const s = getComputedStyle(a);
                return {href: a.getAttribute('href'), text: a.textContent.trim(),
                        opacity: s.opacity, title: a.getAttribute('title')};
            }"""
        )
        results.append(
            ("task row shows a 📧 mailto link",
             bool(mail) and mail["href"].startswith("mailto:")
             and "subject=" in mail["href"] and "body=" in mail["href"]
             and mail["text"] == "📧",
             {k: (v[:60] if k == "href" else v) for k, v in (mail or {}).items()}),
        )
        page.screenshot(path=os.path.join(SHOTS, "5_tasks_rtl.png"), full_page=True)

        # --- Per-task note (Hebrew expander + optimistic save) ---------------------
        page.get_by_text("הערות (", exact=False).first.click()
        page.wait_for_timeout(800)
        note_text = "הערה לבדיקה"
        page.locator('[class*="st-key-comment_text_"] textarea').first.fill(note_text)
        page.get_by_role("button", name="שמירת הערה").first.click()
        page.wait_for_timeout(1500)
        note_visible = page.get_by_text(note_text).count() > 0
        results.append(("task note saved and visible (Hebrew UI)", note_visible, note_visible))
        page.screenshot(path=os.path.join(SHOTS, "5b_task_note.png"), full_page=True)

        # --- Chat tab (avatar side + optimistic echo) -----------------------------
        page.get_by_role("tab", name="תקשורת צוות").click()
        page.wait_for_timeout(1200)
        page.get_by_placeholder("כתבו הודעה לצוות...").fill("שלום צוות — בדיקת RTL")
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

        # --- Home button returns to the bubbles screen -----------------------------
        home = page.get_by_role("button", name="🏠 דף הבית")
        results.append(("home button present in sidebar", home.count() > 0, home.count()))
        home.first.click()
        page.wait_for_timeout(2000)
        back_home = page.get_by_text("ברוך הבא", exact=False).count() > 0
        bubbles_back = page.locator(".st-key-project_bubbles button").count() > 0
        results.append(("home button clears the project and shows the greeting", back_home, back_home))
        results.append(("home screen shows the project bubbles again", bubbles_back, bubbles_back))
        page.screenshot(path=os.path.join(SHOTS, "7_home_button.png"), full_page=True)

        browser.close()

    print()
    ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}: {name}  [{detail}]")
        ok &= bool(passed)
    print("\n" + ("ALL UI CHECKS PASSED" if ok else "SOME UI CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    unseed()  # clear leftovers from any previously aborted run
    server = None
    try:
        seed()
        server = start_server()
        code = main()
    finally:
        if server is not None:
            server.kill()
        unseed()
    sys.exit(code)
