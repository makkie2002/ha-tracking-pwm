"""Diagnostic sensors for the Tracking PWM relay device."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util

from .const import DOMAIN, device_info_for
from .controller import Tracker


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tracking PWM diagnostic sensors."""
    runtime = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if runtime is None:
        return
    tracker: Tracker = runtime["tracker"]
    output: str = runtime["output"]
    name: str = runtime["name"]
    entry_id = config_entry.entry_id
    async_add_entities(
        [
            _DebtSensor(entry_id, output, name, tracker),
            _WantedSensor(entry_id, output, name, tracker),
            _WantedFilteredSensor(entry_id, output, name, tracker),
            _SecondsSinceSwitchSensor(entry_id, output, name, tracker),
            _DwellRemainingSensor(entry_id, output, name, tracker),
            _CycleRemainingSensor(entry_id, output, name, tracker),
            _LastOnSensor(entry_id, output, name, tracker),
            _LastOffSensor(entry_id, output, name, tracker),
            _SwitchCountSensor(entry_id, output, name, tracker),
        ]
    )


class _DiagnosticSensor(SensorEntity):
    """Base class: push-updated diagnostic sensor reading the tracker."""

    _key = "diagnostic"
    _label = "Diagnostic"

    def __init__(
        self, entry_id: str, output: str, name: str, tracker: Tracker
    ) -> None:
        """Initialize a diagnostic sensor."""
        self._output = output
        self._device_name = name
        self._tracker = tracker
        self._attr_name = f"{name} {self._label}"
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = False
        super().__init__()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the relay device."""
        return device_info_for(self._output, self._device_name)

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracker evaluations."""
        await super().async_added_to_hass()
        self._tracker.subscribe(self._handle_tracker_update)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from tracker evaluations."""
        self._tracker.unsubscribe(self._handle_tracker_update)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_tracker_update(self) -> None:
        """Write fresh state after each tracker evaluation."""
        self.async_write_ha_state()

    @property
    def native_value(self):
        """Return the sensor value."""
        raise NotImplementedError


class _DebtSensor(_DiagnosticSensor):
    """Integrated over-delivery in seconds of full output."""

    _key = "delivery_debt"
    _label = "delivery debt"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the debt sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return the delivery debt."""
        return round(self._tracker.debt, 1)


class _WantedSensor(_DiagnosticSensor):
    """Wanted duty in percent."""

    _key = "wanted_duty"
    _label = "wanted duty"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the wanted-duty sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return the wanted duty in percent."""
        return round(self._tracker.wanted * 100.0, 1)


class _WantedFilteredSensor(_DiagnosticSensor):
    """Slow (1h default) low-pass of the wanted duty, in percent."""

    _key = "wanted_duty_filtered"
    _label = "wanted duty filtered"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the filtered-wanted sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        """Return the filtered wanted duty in percent, if sampled yet."""
        value = self._tracker.wanted_smooth
        return None if value is None else round(value * 100.0, 1)


class _SecondsSinceSwitchSensor(_DiagnosticSensor):
    """Seconds since the last relay flip."""

    _key = "seconds_since_switch"
    _label = "seconds since switch"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the timer sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        """Return seconds since the last flip, None if never flipped."""
        value = self._tracker.seconds_since(
            dt_util.utcnow().replace(microsecond=0), "switch"
        )
        return None if value is None else round(value, 1)


class _DwellRemainingSensor(_DiagnosticSensor):
    """Seconds until the dwell guard releases (0 when not holding)."""

    _key = "dwell_remaining"
    _label = "dwell remaining"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return the remaining dwell hold in seconds."""
        return round(
            self._tracker.hold_remaining(dt_util.utcnow().replace(microsecond=0), "dwell"),
            1,
        )


class _CycleRemainingSensor(_DiagnosticSensor):
    """Seconds until a new cycle may start (0 when not holding)."""

    _key = "cycle_remaining"
    _label = "cycle remaining"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float:
        """Return the remaining cycle hold in seconds."""
        return round(
            self._tracker.hold_remaining(dt_util.utcnow().replace(microsecond=0), "cycle"),
            1,
        )


class _LastOnSensor(_DiagnosticSensor):
    """Length of the most recent completed on-phase in seconds."""

    _key = "last_on_duration"
    _label = "last on duration"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        """Return the last completed on-phase length, if any."""
        value = self._tracker.last_on_duration
        return None if value is None else round(value, 1)


class _LastOffSensor(_DiagnosticSensor):
    """Length of the most recent completed off-phase in seconds."""

    _key = "last_off_duration"
    _label = "last off duration"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = 1

    @property
    def native_value(self) -> float | None:
        """Return the last completed off-phase length, if any."""
        value = self._tracker.last_off_duration
        return None if value is None else round(value, 1)


class _SwitchCountSensor(_DiagnosticSensor):
    """Total relay flips since start."""

    _key = "switch_count"
    _label = "switch count"

    def __init__(self, entry_id, output, name, tracker):
        """Initialize the sensor."""
        super().__init__(entry_id, output, name, tracker)
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_suggested_display_precision = 0

    @property
    def native_value(self) -> int:
        """Return the flip count."""
        return self._tracker.switch_count
