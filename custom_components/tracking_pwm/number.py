"""Number entities: setpoint plus live tuning dials around the Tracker."""
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

try:
    # New cores: consistent *Entity suffix like every other platform.
    from homeassistant.components.number import NumberEntity as NumberBase
except ImportError:
    # Old cores: legacy alias.
    from homeassistant.components.number import Number as NumberBase
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_MAXIMUM,
    CONF_MINIMUM,
    CONF_MODE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PERCENTAGE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import CoreState, HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
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
    DOMAIN,
    MODE_AUTO,
    MODE_BOX,
    MODE_SLIDER,
    as_timedelta,
    device_info_for,
    normalize_outputs,
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Tracking PWM config entry: setpoint plus live dials."""
    runtime = hass.data[DOMAIN][config_entry.entry_id]
    tracker: Tracker = runtime["tracker"]
    output: str = runtime["output"]
    name: str = runtime["name"]
    entry_id = config_entry.entry_id
    setpoint = TrackingPWMEntity(hass, config_entry.options, entry_id, tracker)
    async_add_entities(
        [
            setpoint,
            DwellDial(hass, entry_id, output, name, tracker, tracker.dwell),
            CycleDial(hass, entry_id, output, name, tracker, tracker.min_cycle),
            IntervalDial(hass, entry_id, output, name, tracker, setpoint),
        ]
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    _discovery_info: Any | None = None,
) -> None:
    """Set up the tracking PWM number platform (YAML: setpoint only)."""
    from . import build_tracker

    output = normalize_outputs(config[CONF_OUTPUTS])[0]
    tracker = build_tracker(config)
    async_add_entities(
        [TrackingPWMEntity(hass, config, config.get(CONF_UNIQUE_ID), tracker)]
    )


class TrackingPWMEntity(RestoreNumber):
    """A number whose value is the wanted duty of a single relay."""

    def __init__(
        self, hass: HomeAssistant, config, unique_id: str | None, tracker: Tracker
    ) -> None:
        """Initialize the Tracking PWM number."""
        self._hass = hass
        self._output = normalize_outputs(config[CONF_OUTPUTS])[0]
        self._attr_name = config.get(CONF_NAME, "TRACKING_PWM_NUMBER")
        self._attr_unique_id = unique_id
        self._attr_native_min_value = config.get(CONF_MINIMUM, DEFAULT_MIN_VALUE)
        self._attr_native_max_value = config.get(CONF_MAXIMUM, DEFAULT_MAX_VALUE)
        self._attr_native_step = config.get(CONF_STEP, DEFAULT_STEP)
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_mode = config.get(CONF_MODE, DEFAULT_MODE)
        self._interval = as_timedelta(
            config.get(CONF_UPDATE_INTERVAL), DEFAULT_UPDATE_INTERVAL
        )
        if self._interval.total_seconds() < 1:
            _LOGGER.warning(
                "update_interval %s too small, clamped to 1 second",
                self._interval,
            )
            self._interval = timedelta(seconds=1)
        self._range = self._attr_native_max_value - self._attr_native_min_value
        self._attr_native_value = config.get(CONF_MINIMUM, DEFAULT_MIN_VALUE)
        self._tracker = tracker
        self._listener_tick = None
        super().__init__()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the relay device."""
        return device_info_for(self._output, self._attr_name)

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
        # Restore setpoint; the debt restarts at 0 and re-derives the relay.
        if last_data := await self.async_get_last_number_data():
            self._attr_native_value = float(last_data.native_value)

        self._listener_tick = async_track_time_interval(
            self._hass, self._async_tick, self._interval
        )

        # After full startup, evaluate once to assert the relay state.
        async def _async_startup(_event=None):
            await self._async_evaluate(
                dt_util.utcnow().replace(microsecond=0), force=True
            )
            self.async_write_ha_state()

        if self._hass.state == CoreState.running:
            await _async_startup()
        else:
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity about to be removed from hass."""
        await super().async_will_remove_from_hass()
        if self._listener_tick:
            self._listener_tick()
            self._listener_tick = None

    async def async_set_interval(self, seconds: float) -> None:
        """Change the evaluation interval live (config dial)."""
        seconds = max(1.0, float(seconds))
        self._interval = timedelta(seconds=seconds)
        if self._listener_tick:
            self._listener_tick()
            self._listener_tick = None
        self._listener_tick = async_track_time_interval(
            self._hass, self._async_tick, self._interval
        )

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    async def async_set_native_value(self, value: float) -> None:
        """Set new wanted duty and evaluate immediately."""
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
        """Advance the tracker, switch the relay on change, notify sensors."""
        _, changed = self._tracker.update(now, self._duty(self._attr_native_value))
        if changed or force:
            await self._hass.services.async_call(
                "homeassistant",
                SERVICE_TURN_ON if self._tracker.relay_on else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self._output},
                True,
            )
        self._tracker.notify()
        return changed

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Return capability attributes."""
        attr = super().capability_attributes
        attr[ATTR_MIN_SWITCH_TIME] = str(timedelta(seconds=self._tracker.dwell))
        attr[ATTR_MIN_CYCLE_PERIOD] = str(timedelta(seconds=self._tracker.min_cycle))
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


class _DialBase(NumberBase):
    """Base class for live tuning dials (config entity category)."""

    _key = "dial"
    _label = "Dial"
    _min = 0.0
    _max = 3600.0

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        output: str,
        name: str,
        tracker: Tracker,
        initial: float,
    ) -> None:
        """Initialize a tuning dial."""
        self._hass = hass
        self._output = output
        self._device_name = name
        self._tracker = tracker
        self._attr_name = f"{name} {self._label}"
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_native_min_value = self._min
        self._attr_native_max_value = self._max
        self._attr_native_step = 1.0
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_suggested_display_precision = 0
        self._attr_mode = MODE_BOX
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_value = float(initial)
        super().__init__()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the relay device."""
        return device_info_for(self._output, self._device_name)

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    async def async_set_native_value(self, value: float) -> None:
        """Apply the new value live and store it."""
        if isnan(value):
            _LOGGER.warning("Invalid value for tracking_pwm %s: %s", self._key, value)
            return
        await self._async_apply(value)
        self._attr_native_value = float(value)
        self.async_write_ha_state()

    async def _async_apply(self, value: float) -> None:
        """Apply the value to the running tracker (overridden)."""
        raise NotImplementedError


class DwellDial(_DialBase):
    """Live dwell guard in seconds."""

    _key = "dwell"
    _label = "dwell"

    async def _async_apply(self, value: float) -> None:
        """Apply the dwell live."""
        self._tracker.configure(dwell_s=max(0.0, float(value)))


class CycleDial(_DialBase):
    """Live minimum cycle period in seconds (0 restores auto = 2x dwell)."""

    _key = "min_cycle"
    _label = "minimum cycle"

    async def _async_apply(self, value: float) -> None:
        """Apply the minimum cycle period live."""
        value = float(value)
        self._tracker.configure(
            min_cycle_s=value if value > 0 else 2.0 * self._tracker.dwell
        )


class IntervalDial(_DialBase):
    """Live evaluation interval in seconds."""

    _key = "update_interval"
    _label = "update interval"
    _min = 1.0
    _max = 3600.0

    def __init__(self, hass, entry_id, output, name, tracker, setpoint) -> None:
        """Initialize the interval dial with a link to the setpoint entity."""
        self._setpoint = setpoint
        super().__init__(
            hass,
            entry_id,
            output,
            name,
            tracker,
            setpoint._interval.total_seconds(),
        )

    async def _async_apply(self, value: float) -> None:
        """Re-arm the setpoint evaluation timer."""
        await self._setpoint.async_set_interval(value)
