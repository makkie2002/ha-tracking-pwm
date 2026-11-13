"""Number entity: thin Home Assistant wrapper around the Tracker."""
from __future__ import annotations

from datetime import timedelta
import logging
from math import isnan
from typing import Any

import voluptuous as vol

from homeassistant.components.number import (
    DEFAULT_MAX_VALUE,
    DEFAULT_MIN_VALUE,
    DEFAULT_STEP,
    PLATFORM_SCHEMA,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_MAXIMUM,
    CONF_MINIMUM,
    CONF_MODE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import CoreState, HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    ATTR_CYCLE_REMAINING,
    ATTR_DELIVERY_DEBT,
    ATTR_DWELL_REMAINING,
    ATTR_LAST_OFF_DURATION,
    ATTR_LAST_ON_DURATION,
    ATTR_MIN_CYCLE_PERIOD,
    ATTR_MIN_SWITCH_TIME,
    ATTR_OUTPUT_STATES,
    ATTR_SECONDS_SINCE_SWITCH,
    ATTR_SWITCH_COUNT,
    ATTR_UPDATE_INTERVAL,
    ATTR_WANTED_DUTY,
    CONF_MIN_CYCLE_PERIOD,
    CONF_MIN_SWITCH_TIME,
    CONF_OUTPUTS,
    CONF_STEP,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MODE,
    DEFAULT_SWITCH_TIME,
    DEFAULT_UPDATE_INTERVAL,
    MODE_AUTO,
    MODE_BOX,
    MODE_SLIDER,
)
from .controller import Tracker

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_OUTPUTS): vol.All(
            cv.entity_ids, vol.Length(min=1, max=1)
        ),
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_MINIMUM, default=DEFAULT_MIN_VALUE): vol.Coerce(float),
        vol.Optional(CONF_MAXIMUM, default=DEFAULT_MAX_VALUE): vol.Coerce(float),
        vol.Optional(
            CONF_MIN_SWITCH_TIME, default=DEFAULT_SWITCH_TIME
        ): cv.time_period_dict,
        vol.Optional(CONF_MIN_CYCLE_PERIOD): cv.time_period_dict,
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
        ): cv.time_period_dict,
        vol.Optional(CONF_STEP, default=DEFAULT_STEP): cv.positive_float,
        vol.Optional(CONF_MODE, default=MODE_SLIDER): vol.In(
            [MODE_BOX, MODE_SLIDER, MODE_AUTO]
        ),
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)


def _as_timedelta(value: Any, default: dict) -> timedelta:
    """Parse a time_period_dict (or timedelta) config value."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, dict):
        return timedelta(**value)
    return timedelta(**default)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Tracking PWM config entry."""
    async_add_entities(
        [TrackingPWMEntity(hass, config_entry.options, config_entry.entry_id)]
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    _discovery_info: Any | None = None,
) -> None:
    """Set up the slow PWM number platform."""
    async_add_entities([TrackingPWMEntity(hass, config, config.get(CONF_UNIQUE_ID))])


class TrackingPWMEntity(RestoreNumber):
    """A number whose value is the wanted duty of a single relay."""

    def __init__(self, hass: HomeAssistant, config, unique_id: str | None) -> None:
        """Initialize the Slow PWM number."""
        self._hass = hass
        self._attr_name = config.get(CONF_NAME, "TRACKING_PWM_NUMBER")
        self._attr_unique_id = unique_id
        self._attr_native_min_value = config.get(CONF_MINIMUM, DEFAULT_MIN_VALUE)
        self._attr_native_max_value = config.get(CONF_MAXIMUM, DEFAULT_MAX_VALUE)
        self._attr_native_step = config.get(CONF_STEP, DEFAULT_STEP)
        self._attr_mode = config.get(CONF_MODE, DEFAULT_MODE)
        self._dwell = _as_timedelta(
            config.get(CONF_MIN_SWITCH_TIME), DEFAULT_SWITCH_TIME
        )
        self._interval = _as_timedelta(
            config.get(CONF_UPDATE_INTERVAL), DEFAULT_UPDATE_INTERVAL
        )
        if self._interval.total_seconds() < 1:
            _LOGGER.warning(
                "update_interval %s too small, clamped to 1 second",
                self._interval,
            )
            self._interval = timedelta(seconds=1)
        outputs = config[CONF_OUTPUTS]
        if isinstance(outputs, str):
            outputs = [outputs]
        if len(outputs) != 1:
            raise ValueError(
                f"tracking_pwm supports exactly one output relay, got {len(outputs)}"
            )
        self._output = outputs[0]
        self._range = self._attr_native_max_value - self._attr_native_min_value
        self._attr_native_value = config.get(CONF_MINIMUM, DEFAULT_MIN_VALUE)
        raw_period = config.get(CONF_MIN_CYCLE_PERIOD)
        period_s: float | None = None
        if raw_period is not None:
            period_s = _as_timedelta(raw_period, DEFAULT_SWITCH_TIME).total_seconds()
            if period_s < 2.0 * self._dwell.total_seconds():
                _LOGGER.warning(
                    "minimal_cycle_period %s smaller than 2x dwell %s, clamped",
                    _as_timedelta(raw_period, DEFAULT_SWITCH_TIME),
                    self._dwell,
                )
                period_s = None  # Tracker falls back to 2x dwell
        self._tracker = Tracker(
            dwell_s=self._dwell.total_seconds(),
            min_cycle_s=period_s,
        )
        self._min_period = self._tracker.min_cycle
        self._listener_tick = None
        super().__init__()

    def _duty(self, value: float) -> float:
        """Normalize a native value to duty 0..1."""
        if self._range <= 0:
            return 0.0
        duty = (value - self._attr_native_min_value) / self._range
        if duty < 0.0:
            return 0.0
        if duty > 1.0:
            return 1.0
        return duty

    async def async_added_to_hass(self) -> None:
        """Handle entity about to be added to hass event."""
        await super().async_added_to_hass()
        if last_data := await self.async_get_last_number_data():
            self._attr_native_value = float(last_data.native_value)

        self._listener_tick = async_track_time_interval(
            self.hass, self._async_tick, self._interval
        )

        async def _async_startup(_event=None):
            await self._async_evaluate(
                dt_util.utcnow().replace(microsecond=0), force=True
            )
            self.async_write_ha_state()

        if self.hass.state == CoreState.running:
            await _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity about to be removed from hass."""
        await super().async_will_remove_from_hass()
        if self._listener_tick:
            self._listener_tick()
            self._listener_tick = None

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    async def async_set_native_value(self, value: float) -> None:
        """Set new wanted value and evaluate immediately."""
        if isnan(value):
            _LOGGER.warning("Invalid value for tracking_pwm: %s", value)
            return
        self._attr_native_value = value
        await self._async_evaluate(dt_util.utcnow().replace(microsecond=0))
        self.async_write_ha_state()

    async def _async_tick(self, now) -> None:
        """Periodic evaluation so the dither continues without new writes."""
        await self._async_evaluate(now.replace(microsecond=0))
        self.async_write_ha_state()

    async def _async_evaluate(self, now, force: bool = False) -> bool:
        """Advance the tracker and switch the relay on change."""
        _, changed = self._tracker.update(now, self._duty(self._attr_native_value))
        if changed or force:
            await self._hass.services.async_call(
                "homeassistant",
                SERVICE_TURN_ON if self._tracker.relay_on else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self._output},
                True,
            )
            return True
        return False

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Return capability attributes."""
        attr = super().capability_attributes
        attr[ATTR_MIN_SWITCH_TIME] = str(self._dwell)
        attr[ATTR_MIN_CYCLE_PERIOD] = str(timedelta(seconds=self._min_period))
        attr[ATTR_UPDATE_INTERVAL] = str(self._interval)
        return attr

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the optional state attributes."""
        now = dt_util.utcnow().replace(microsecond=0)
        return {
            ATTR_OUTPUT_STATES: {self._output: self._tracker.relay_on},
            ATTR_WANTED_DUTY: self._duty(self._attr_native_value),
            ATTR_DELIVERY_DEBT: self._tracker.debt,
            ATTR_SECONDS_SINCE_SWITCH: self._tracker.seconds_since(now, "switch"),
            ATTR_DWELL_REMAINING: self._tracker.hold_remaining(now, "dwell"),
            ATTR_CYCLE_REMAINING: self._tracker.hold_remaining(now, "cycle"),
            ATTR_LAST_ON_DURATION: self._tracker.last_on_duration,
            ATTR_LAST_OFF_DURATION: self._tracker.last_off_duration,
            ATTR_SWITCH_COUNT: self._tracker.switch_count,
        }
