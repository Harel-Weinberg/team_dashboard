"""
optimistic.py — Optimistic UI engine: instant local echo + background DB sync.

How it works:
  * submit_write() runs a database write on a background thread pool and
    tracks its Future in st.session_state, so the UI rerun never blocks on
    the network round-trip to Supabase.
  * UI components append a local "echo" of the change (message / task /
    comment) to st.session_state and render it immediately, marked 🕓.
  * surviving_echoes() prunes echoes once the write has landed and shows up
    in a fresh DB read (writes clear the relevant st.cache_data caches).
  * report_sync_failures() runs at the top of every rerun and surfaces any
    failed background write as a warning, so a lost write is never silent —
    the UI then falls back to the database's truth.

Thread-safety: database.py uses a ThreadedConnectionPool, so worker threads
each get their own connection. Workers never touch st.session_state — only
the main script thread reads the Futures.
"""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait

import streamlit as st

_PENDING_KEY = "_pending_writes"


@st.cache_resource(show_spinner=False)
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=4, thread_name_prefix="db-sync")


def submit_write(description: str, fn: Callable, /, *args, **kwargs) -> Future:
    """Run a DB write in the background; track it so failures surface in the UI."""
    future = _executor().submit(fn, *args, **kwargs)
    st.session_state.setdefault(_PENDING_KEY, []).append(
        {"future": future, "description": description}
    )
    return future


def wait_for_pending(timeout: float = 8.0) -> bool:
    """Block until tracked background writes finish. Returns True if all landed.

    Used before operations that must not race with in-flight writes — e.g.
    renaming a user, where a late write would still carry the old username.
    """
    futures = [item["future"] for item in st.session_state.get(_PENDING_KEY, [])]
    if not futures:
        return True
    _, not_done = futures_wait(futures, timeout=timeout)
    return not not_done


def discard_echoes() -> None:
    """Drop local echo overlays (their writes already went to the database).

    Called after a username change: echoes are matched against the DB by
    author name, so stale echoes tagged with the old name would never be
    pruned and would linger as visual duplicates.
    """
    for key in [k for k in st.session_state if str(k).startswith("optimistic_")]:
        st.session_state.pop(key, None)
    st.session_state.pop("task_done_override", None)


def report_sync_failures() -> None:
    """Call at the top of every rerun: warn about failed background writes."""
    keep = []
    for item in st.session_state.get(_PENDING_KEY, []):
        if item["future"].done():
            exc = item["future"].exception()
            if exc is not None:
                st.warning(
                    f"⚠️ Could not sync **{item['description']}** to the database: {exc} — "
                    "the change was not saved. Please retry, or press 🔄 Refresh."
                )
        else:
            keep.append(item)
    st.session_state[_PENDING_KEY] = keep


def surviving_echoes(echoes: list[dict], landed: Callable[[dict], bool]) -> list[dict]:
    """Prune local echoes whose write finished.

    An echo is dropped when its write failed (report_sync_failures shows the
    warning; the UI reverts to DB truth) or when it succeeded AND the item is
    visible in the current fresh read (no flicker between echo and DB row).
    """
    keep = []
    for echo in echoes:
        future = echo["future"]
        if future.done() and future.exception() is not None:
            continue
        if future.done() and landed(echo):
            continue
        keep.append(echo)
    return keep
