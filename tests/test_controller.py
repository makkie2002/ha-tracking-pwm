"""Unit tests for the pure sigma-delta tracker. No Home Assistant needed."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Import controller.py by file path: it has zero dependencies, and this
# avoids executing the HA-dependent package __init__.
_spec = importlib.util.spec_from_file_location(
    "tracking_controller",
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "tracking_pwm"
    / "controller.py",
)
_controller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_controller)
Tracker = _controller.Tracker


def T0():
    return datetime.now(timezone.utc).replace(microsecond=0)


def run(w, dwell=120.0, min_cycle=None, tick=30.0, minutes=720.0):
    """Drive a tracker with constant wanted duty; return relay trace."""
    tr = Tracker(dwell_s=dwell, min_cycle_s=min_cycle)
    now = T0()
    out = []
    n = int(minutes * 60 / tick)
    for _ in range(n):
        now = now + timedelta(seconds=tick)
        on, _ = tr.update(now, w)
        out.append(on)
    return tr, out


def test_on_off_no_dwell():
    tr = Tracker(dwell_s=0.0)
    now = T0()
    assert tr.update(now, 1.0) == (True, True)
    assert tr.update(now, 0.0) == (False, True)
    assert tr.update(now, 0.0) == (False, False)  # no repeat calls


def test_wanted_zero_never_turns_on():
    tr = Tracker(dwell_s=0.0)
    now = T0()
    assert tr.update(now, 0.0) == (False, False)


def test_dwell_holds_both_directions():
    tr = Tracker(dwell_s=120.0)
    now = T0()
    assert tr.update(now, 0.5) == (True, True)
    # 30s later debt wants off, dwell holds on
    assert tr.update(now + timedelta(seconds=30), 0.5) == (True, False)
    # after dwell expiry it flips off...
    assert tr.update(now + timedelta(seconds=121), 0.5) == (False, True)
    # ...and the fresh on-phase is held off by the dwell too
    assert tr.update(now + timedelta(seconds=151), 0.5) == (False, False)


def test_average_exact_across_duties():
    for w, expect in [(0.02, 0.02), (0.05, 0.05), (0.15, 0.15), (0.5, 0.5),
                      (0.6, 0.6), (0.8, 0.8), (0.95, 0.95), (1.0, 1.0)]:
        _, out = run(w, dwell=120.0, minutes=720.0)
        avg = sum(out) / len(out)
        assert abs(avg - expect) < 0.01, (w, avg)


def test_low_duty_repaid_exactly():
    # 5% with 2min dwell: 120s on, then ~38min off per cycle.
    tr = Tracker(dwell_s=120.0)
    now = T0()
    assert tr.update(now, 0.05) == (True, True)
    assert tr.update(now + timedelta(seconds=120), 0.05) == (False, True)
    assert tr.update(now + timedelta(seconds=1320), 0.05) == (False, False)
    assert tr.update(now + timedelta(seconds=2520), 0.05) == (True, True)


def test_step_up_bounded_delay():
    tr = Tracker(dwell_s=120.0)
    now = T0()
    assert tr.update(now, 0.05) == (True, True)
    assert tr.update(now + timedelta(seconds=120), 0.05) == (False, True)
    # step up while debt unpaid: holds off, then fires
    assert tr.update(now + timedelta(seconds=130), 0.6) == (False, False)
    assert tr.update(now + timedelta(seconds=330), 0.6) == (True, True)


def test_min_cycle_period_caps_rate():
    tr = Tracker(dwell_s=120.0, min_cycle_s=600.0)
    now = T0()
    assert tr.update(now, 0.5) == (True, True)
    assert tr.update(now + timedelta(seconds=120), 0.5) == (False, True)
    # debt repaid and dwell expired, but cycle is only 300s old -> hold
    assert tr.update(now + timedelta(seconds=300), 0.5) == (False, False)
    # at 600s the new cycle may start
    assert tr.update(now + timedelta(seconds=600), 0.5) == (True, True)


def test_min_cycle_defaults_to_twice_dwell():
    assert Tracker(dwell_s=120.0).min_cycle == 240.0
    assert Tracker(dwell_s=120.0, min_cycle_s=60.0).min_cycle == 240.0


def test_debt_clamped():
    tr = Tracker(dwell_s=120.0)
    now = T0()
    tr.update(now, 0.5)
    tr.update(now + timedelta(seconds=10**6), 0.5)
    assert abs(tr.debt) <= tr.debt_limit


def test_wanted_clamped_to_unit_interval():
    tr = Tracker(dwell_s=0.0)
    now = T0()
    assert tr.update(now, 999.0)[0] is True
    assert tr.update(now, -5.0)[0] is False


def test_diagnostics_bookkeeping():
    tr = Tracker(dwell_s=120.0)
    now = T0()
    assert tr.update(now, 0.5) == (True, True)
    assert tr.switch_count == 1
    assert tr.last_on_duration is None  # no completed phase yet
    assert tr.last_off_duration is None
    assert tr.seconds_since(now, "switch") == 0.0
    assert tr.seconds_since(now, "cycle") == 0.0
    assert tr.hold_remaining(now, "dwell") == 120.0
    assert tr.hold_remaining(now, "cycle") == 240.0  # auto 2x dwell
    assert tr.update(now + timedelta(seconds=120), 0.5) == (False, True)
    assert tr.last_on_duration == 120.0
    assert tr.switch_count == 2
    later = now + timedelta(seconds=150)
    assert tr.seconds_since(later, "switch") == 30.0
    assert tr.hold_remaining(later, "dwell") == 90.0
    with pytest.raises(ValueError):
        tr.hold_remaining(later, "bogus")


def test_configure_updates_live():
    tr = Tracker(dwell_s=120.0)
    assert tr.configure(dwell_s=60.0) == {"dwell": 60.0, "min_cycle": 240.0}
    assert tr.min_cycle == 240.0  # unchanged, still >= 2x dwell
    assert tr.configure(min_cycle_s=30.0) == {"dwell": 60.0, "min_cycle": 120.0}
    assert tr.min_cycle == 120.0  # clamped to 2x dwell


def test_configure_rescales_debt_limit():
    tr = Tracker(dwell_s=120.0)
    assert tr.debt_limit == max(8 * 120.0, 2 * 240.0, 600.0)
    tr.configure(dwell_s=600.0)
    assert tr.debt_limit == max(8 * 600.0, 2 * 1200.0, 600.0)
    tr.debt = 999999.0
    tr.configure(dwell_s=60.0)  # min_cycle stays 1200 from before
    assert tr.debt == max(8 * 60.0, 2 * 1200.0, 600.0)


def test_listeners_notified():
    tr = Tracker(dwell_s=0.0)
    calls = []

    def cb():
        calls.append(1)

    tr.subscribe(cb)
    tr.notify()
    assert calls == [1]
    tr.unsubscribe(cb)
    tr.notify()
    assert calls == [1]
    tr.unsubscribe(cb)  # no error when absent
