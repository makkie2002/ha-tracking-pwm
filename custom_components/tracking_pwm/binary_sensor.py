"""Relay state binary sensor for the Tracking PWM device."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, device_info_for
from .controller import Tracker


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tracking PWM relay binary sensor."""
    runtime = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if runtime is None:
        return
    async_add_entities(
        [
            TrackingRelaySensor(
                config_entry.entry_id,
                runtime["output"],
                runtime["name"],
                runtime["tracker"],
            )
        ]
    )


class TrackingRelaySensor(BinarySensorEntity):
    """On/off state of the tracked relay."""

    def __init__(self, entry_id: str, output: str, name: str, tracker: Tracker) -> None:
        """Initialize the relay binary sensor."""
        self._output = output
        self._device_name = name
        self._tracker = tracker
        self._attr_name = f"{name} relay"
        self._attr_unique_id = f"{entry_id}_relay"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_should_poll = False
        super().__init__()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the relay device."""
        return device_info_for(self._output, self._device_name)

    @property
    def is_on(self) -> bool:
        """Return True when the relay output is on."""
        return self._tracker.relay_on

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
