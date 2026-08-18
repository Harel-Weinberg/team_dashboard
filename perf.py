"""perf.py — Opt-in render-phase timing.

Disabled unless the DASH_PERF environment variable is set, so the timing hooks
can stay in the code permanently at zero cost in production: when off, timed()
is a no-op contextmanager and record() returns immediately.

Enable with:  DASH_PERF=1 python bench_nav.py
"""

import functools
import os
import time
from collections import defaultdict
from contextlib import contextmanager

ENABLED = bool(os.environ.get("DASH_PERF"))

# label -> list of durations in ms, across every run since the last reset().
SAMPLES: dict[str, list[float]] = defaultdict(list)

# Set by the bench between scenarios so samples can be attributed to a phase.
_scenario = "default"


def scenario(name: str) -> None:
    global _scenario
    _scenario = name


def reset() -> None:
    SAMPLES.clear()


@contextmanager
def timed(label: str):
    if not ENABLED:
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        SAMPLES[f"{_scenario}/{label}"].append((time.perf_counter() - t0) * 1000)


def report(title: str = "") -> str:
    """Format collected samples as a table: label, n, mean, max."""
    if not SAMPLES:
        return f"{title}\n  (no samples — is DASH_PERF set?)"
    width = max(len(k) for k in SAMPLES)
    lines = [title] if title else []
    lines.append(f"  {'phase'.ljust(width)}   n   mean      max")
    for label in sorted(SAMPLES):
        xs = SAMPLES[label]
        lines.append(
            f"  {label.ljust(width)} {len(xs):3d}  {sum(xs) / len(xs):6.1f}ms  {max(xs):6.1f}ms"
        )
    return "\n".join(lines)


def track(label: str):
    """Decorator form of timed(). Returns the function unchanged when disabled,
    so instrumented code carries no wrapper in production."""
    def decorator(fn):
        if not ENABLED:
            return fn

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with timed(label):
                return fn(*args, **kwargs)

        return wrapper

    return decorator
