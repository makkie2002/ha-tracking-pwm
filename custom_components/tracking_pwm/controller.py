"""Pure sigma-delta tracking PWM for a single relay.

Bresenham-style error feedback: each evaluation integrates the delivery
error ``debt += (actual - wanted) * dt``. The relay is ON whenever output
is owed (debt <= 0 and wanted > 0) and OFF whenever over-delivery is
unpaid
(debt > 0). A dwell guard enforces minimum on/off times for relay
protection and a minimum cycle period caps the switching rate; the debt
repays both exactly, so the long-term average equals wanted at any duty.

A slow diagnostic low-pass of the setpoint (``wanted_smooth``) is
maintained alongside the controller but never drives the relay.

This module has no Home Assistant dependencies and is fully unit-testable.
Time is expressed in seconds; ``now`` only needs to support subtraction
yielding an object with ``total_seconds()`` (e.g. ``datetime``).
"""
from __future__ import annotations

from math import exp


class Tracker:
    """First-order sigma-delta relay tracker with dwell and cycle guards."""

    def __init__(
        self,
        dwell_s: float = 120.0,
        min_cycle_s: float | None = None,
        debt_limit_s: float | None = None,
        wanted_tau_s: float | None = 3600.0,
    ) -> None:
        """Initialize the tracker.

        dwell_s: minimum seconds the relay stays on or off before flipping.
        min_cycle_s: minimum seconds between cycle starts (OFF->ON flips).
            Defaults to twice the dwell; smaller values are clamped to it.
        debt_limit_s: anti-windup clamp for the integrator. Defaults to
            max(8 * dwell, 2 * min_cycle, 600).
        wanted_tau_s: time constant in seconds for the diagnostic low-pass
            of the wanted duty. Defaults to one hour; 0 or negative
            disables filtering (tracks raw). Never drives the relay.
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
        self.wanted = 0.0
        self.wanted_smooth: float | None = None
        self.wanted_tau = (
            max(0.0, float(wanted_tau_s)) if wanted_tau_s else 0.0
        )
        self.switch_count = 0
        self.last_on_duration: float | None = None
        self.last_off_duration: float | None = None
        self._t_last = None
        self._t_switch = None
        self._t_cycle = None
        self._listeners: list = []

    def update(self, now, wanted: float) -> tuple[bool, bool]:
        """Advance the tracker to ``now`` with duty ``wanted`` (0..1).

        Returns ``(relay_on, changed)``. The wanted value is clamped to
        0..1; a wanted duty of 0 always means off.
        """
        wanted = min(1.0, max(0.0, float(wanted)))
        self.wanted = wanted
        if self._t_last is None:
            dt = 0.0
        else:
            dt = (now - self._t_last).total_seconds()
            if dt < 0.0:
                dt = 0.0
        self._t_last = now
        if self.wanted_smooth is None or self.wanted_tau <= 0.0:
            # Latch the first sample (and follow raw when disabled) so
            # there is no hour-long ramp from zero after a restart.
            self.wanted_smooth = wanted
        elif dt > 0.0:
            alpha = 1.0 - exp(-dt / self.wanted_tau)
            self.wanted_smooth += alpha * (wanted - self.wanted_smooth)
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

    def configure(
        self, dwell_s: float | None = None, min_cycle_s: float | None = None
    ) -> dict:
        """Live-update dwell/cycle guards; keeps all invariants.

        min_cycle_s of None (or below 2x dwell) falls back to 2x dwell.
        Returns the effective {"dwell": .., "min_cycle": ..} in seconds.
        """
        if dwell_s is not None:
            self.dwell = max(0.0, float(dwell_s))
        if min_cycle_s is None:
            self.min_cycle = max(self.min_cycle, 2.0 * self.dwell)
        else:
            self.min_cycle = max(float(min_cycle_s), 2.0 * self.dwell)
        self.debt_limit = max(8.0 * self.dwell, 2.0 * self.min_cycle, 600.0)
        if self.debt > self.debt_limit:
            self.debt = self.debt_limit
        elif self.debt < -self.debt_limit:
            self.debt = -self.debt_limit
        return {"dwell": self.dwell, "min_cycle": self.min_cycle}

    def subscribe(self, callback) -> None:
        """Register a no-arg callback fired on every explicit notify()."""
        self._listeners.append(callback)

    def unsubscribe(self, callback) -> None:
        """Remove a previously registered callback."""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def notify(self) -> None:
        """Fire all registered callbacks (called by the entity each tick)."""
        for callback in list(self._listeners):
            callback()
