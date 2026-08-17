"""Temporary benchmark: home -> project navigation latency (cold vs warm cache)."""

import statistics
import time

import streamlit as st

import database as db
from test_login_flow import TEMP_ADMIN, TEMP_ADMIN_PW, cleanup, create_temp_admin, login, new_app

TEMP_PROJECT = "temp_test_nav_bench"


def seed():
    create_temp_admin()
    pid = db.add_project(TEMP_PROJECT, TEMP_ADMIN)
    for i in range(6):
        db.add_task(f"משימה {i}", TEMP_ADMIN, TEMP_ADMIN, pid, "project", is_urgent=(i == 0))
    task = db.get_tasks(project_id=pid)[0]
    for i in range(4):
        db.add_comment(task["id"], f"הערה {i}", TEMP_ADMIN)
    for i in range(8):
        db.add_chat_message(pid, f"הודעה {i}", TEMP_ADMIN)
    db.save_spec(pid, "אפיון לדוגמה", TEMP_ADMIN)
    return pid


def unseed():
    with db.get_cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE name = %s", (TEMP_PROJECT,))
        row = cur.fetchone()
    if row:
        db.delete_project(row["id"])
    cleanup()


def bench(pid, rounds=3):
    cold, warm = [], []
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    for _ in range(rounds):
        st.cache_data.clear()  # simulate a cold navigation (TTL expired)
        at.session_state["view"] = ("project", pid)
        t = time.perf_counter()
        at = at.run()
        cold.append((time.perf_counter() - t) * 1000)
        assert not at.exception, at.exception[0] if at.exception else None
        t = time.perf_counter()
        at = at.run()
        warm.append((time.perf_counter() - t) * 1000)
    print(f"COLD navigation (cache empty): avg {statistics.mean(cold):6.0f} ms  {[f'{x:.0f}' for x in cold]}")
    print(f"WARM navigation (cache hit)  : avg {statistics.mean(warm):6.0f} ms  {[f'{x:.0f}' for x in warm]}")


def bench_realistic(pid, rounds=3):
    """The actual user flow: sit on the home screen (prefetch fires), then click."""
    times = []
    at = login(new_app(), TEMP_ADMIN, TEMP_ADMIN_PW)
    for _ in range(rounds):
        st.cache_data.clear()
        at.session_state["view"] = None
        at = at.run()          # home screen render kicks off background prefetch
        time.sleep(1.2)        # user "looks at" the home screen for a moment
        at.session_state["view"] = ("project", pid)
        t = time.perf_counter()
        at = at.run()
        times.append((time.perf_counter() - t) * 1000)
        assert not at.exception, at.exception[0] if at.exception else None
    print(f"REALISTIC (home prefetch->click): avg {statistics.mean(times):6.0f} ms  {[f'{x:.0f}' for x in times]}")


if __name__ == "__main__":
    unseed()
    pid = seed()
    try:
        bench(pid)
        bench_realistic(pid)
    finally:
        unseed()
