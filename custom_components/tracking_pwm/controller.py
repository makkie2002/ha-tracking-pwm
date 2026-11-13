"""Pure sigma-delta tracking PWM for a single relay.

Bresenham-style error feedback: each evaluation integrates the delivery
error ``debt += (actual - wanted) * dt``. The relay is ON whenever output
is owed (debt <= 0 and wanted > 0) and OFF whenever over-delivery is
unpaid
(debt > 0). A dwell guard enforces minimum on/off times for relay
protection and a minimum cycle period caps the switching rate; the debt
repays both exactly, so the long-term average equals wanted at any duty.

This module has no Home Assistant dependencies and is fully unit-testable.
Time is expressed in seconds; ``now`` only needs to support subtraction
yielding an object with ``total_seconds()`` (e.g. ``datetime``).
"""
from __future__ import annotations


class Tracker:
    """First-order sigma-delta relay tracker with dwell and cycle guards."""

    def __init__(
        self,
        dwell_s: float = 120.0,
        min_cycle_s: float | None = None,
        debt_limit_s: float | None = None,
    ) -> None:
        """Initialize the tracker.

        dwell_s: minimum seconds the relay stays on or off before flipping.
        min_cycle_s: minimum seconds between cycle starts (OFF->ON flips).
            Defaults to twice the dwell; smaller values are clamped to it.
        debt_limit_s: anti-windup clamp for the integrator. Defaults to
            max(8 * dwell, 2 * min_cycle, 600).
        """
        dwell_s = max(0.0, float(dwell_s))
        if min_cycle_s is None:
            min_cycle_s = 2.0 * dwell_s
        min_cycle_s = max(float(min_cycle_s), 2.0 * dwell_s)
        if debt_limit_s is None:
            debt_limit_s = max(8.0 * dwell_s, 2.0 * min_cycle_s, 600.0)
        self.dwell = dwell_s
        self.min_cycle = min_cycle_s
        self.debt_limit = float(debt_limit_s)
        self.debt = 0.0
        self.relay_on = False
        self.switch_count = 0
        self.last_on_duration: float | None = None
        self.last_off_duration: float | None = None
        self._t_last = None
        self._t_switch = None
        self._t_cycle = None

    def update(self, now, wanted: float) -> tuple[bool, bool]:
        """Advance the tracker to ``now`` with duty ``wanted`` (0..1).

        Returns ``(relay_on, changed)``. The wanted value is clamped to
        0..1; a wanted duty of 0 always means off.
        """
        wanted = min(1.0, max(0.0, float(wanted)))
        if self._t_last is None:
            dt = 0.0
        else:
            dt = (now - self._t_last).total_seconds()
            if dt < 0.0:
                dt = 0.0
        self._t_last = now
        if dt > 0.0:
            self.debt += ((1.0 if self.relay_on else 0.0) - wanted) * dt
            if self.debt > self.debt_limit:
                self.debt = self.debt_limit
            elif self.debt < -self.debt_limit:
                self.debt = -self.debt_limit
        want_on = wanted > 0.0 and self.debt <= 0.0
        if want_on == self.relay_on:
            return self.relay_on, False
        dwell_s = self.dwell
        if (
            self._t_switch is not None
            and dwell_s > 0
            and (now - self._t_switch).total_seconds() < dwell_s
        ):
            return self.relay_on, False
        if want_on and self._t_cycle is not None:
            if (now - self._t_cycle).total_seconds() < self.min_cycle:
                return self.relay_on, False
        if self._t_switch is not None:
            phase = (now - self._t_switch).total_seconds()
            if self.relay_on:
                self.last_on_duration = phase
            else:
                self.last_off_duration = phase
        self.relay_on = want_on
        self.switch_count += 1
        self._t_switch = now
        if want_on:
            self._t_cycle = now
        return self.relay_on, True

    def seconds_since(self, now, which: str) -> float | None:
        """Seconds since the last switch/cycle event, or None if never."""
        stamp = {"switch": self._t_switch, "cycle": self._t_cycle}.get(which)
        if stamp is None:
            return None
        return max(0.0, (now - stamp).total_seconds())

    def hold_remaining(self, now, which: str) -> float:
        """Seconds until the dwell/cycle guard releases (0 when not holding)."""
        if which == "dwell":
            stamp, span = self._t_switch, self.dwell
        elif which == "cycle":
            stamp, span = self._t_cycle, self.min_cycle
        else:
            raise ValueError(f"unknown guard: {which}")
        if stamp is None:
            return 0.0
        return max(0.0, span - (now - stamp).total_seconds())
