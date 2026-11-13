"""The Tracking PWM integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MIN_CYCLE_PERIOD,
    CONF_MIN_SWITCH_TIME,
    CONF_OUTPUTS,
    CONF_WANTED_SMOOTHING,
    DEFAULT_SWITCH_TIME,
    DEFAULT_WANTED_SMOOTHING,
    DOMAIN,
    as_timedelta,
    normalize_outputs,
)
from .controller import Tracker

PLATFORMS = [Platform.NUMBER, Platform.SENSOR, Platform.BINARY_SENSOR]


def build_tracker(options) -> Tracker:
    """Build a Tracker from config entry options or YAML config."""
    dwell = as_timedelta(
        options.get(CONF_MIN_SWITCH_TIME), DEFAULT_SWITCH_TIME
    ).total_seconds()
    raw_period = options.get(CONF_MIN_CYCLE_PERIOD)
    min_cycle = (
        as_timedelta(raw_period, DEFAULT_SWITCH_TIME).total_seconds()
        if raw_period
        else None
    )
    wanted_tau = as_timedelta(
        options.get(CONF_WANTED_SMOOTHING), DEFAULT_WANTED_SMOOTHING
    ).total_seconds()
    return Tracker(dwell_s=dwell, min_cycle_s=min_cycle, wanted_tau_s=wanted_tau)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tracking PWM from a config entry."""
    options = entry.options
    output = normalize_outputs(options[CONF_OUTPUTS])[0]
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "tracker": build_tracker(options),
        "output": output,
        "name": options.get(CONF_NAME, output),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))
    return True


async def config_entry_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
