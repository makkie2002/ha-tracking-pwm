"""Config flow for tracking_pwm integration."""
from collections.abc import Mapping
import logging
from typing import Any, cast

import voluptuous as vol

from homeassistant.components.number import (
    DEFAULT_MAX_VALUE,
    DEFAULT_MIN_VALUE,
    DEFAULT_STEP,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import CONF_MAXIMUM, CONF_MINIMUM, CONF_MODE, CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
)

from .const import (
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
)

_LOGGER = logging.getLogger(__name__)

_MODES = [
    selector.SelectOptionDict(value=MODE_AUTO, label="Auto"),
    selector.SelectOptionDict(value=MODE_BOX, label="Box"),
    selector.SelectOptionDict(value=MODE_SLIDER, label="Slider"),
]


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_OUTPUTS): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=[SWITCH_DOMAIN],
                multiple=False,
            ),
        ),
        vol.Optional(CONF_MINIMUM, default=DEFAULT_MIN_VALUE): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, mode=selector.NumberSelectorMode.BOX),
        ),
        vol.Optional(CONF_MAXIMUM, default=DEFAULT_MAX_VALUE): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, mode=selector.NumberSelectorMode.BOX),
        ),
        vol.Optional(
            CONF_MIN_SWITCH_TIME, default=DEFAULT_SWITCH_TIME
        ): selector.DurationSelector(),
        vol.Optional(CONF_MIN_CYCLE_PERIOD): selector.DurationSelector(),
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
        ): selector.DurationSelector(),
        vol.Optional(CONF_STEP, default=DEFAULT_STEP): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.001, mode=selector.NumberSelectorMode.BOX
            ),
        ),
        vol.Optional(CONF_MODE, default=DEFAULT_MODE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_MODES),
        ),
    }
)


CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
    }
).extend(OPTIONS_SCHEMA.schema)


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(CONFIG_SCHEMA),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(OPTIONS_SCHEMA),
}


class TrackingPWMConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Tracking PWM config handler."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options["name"]) if CONF_NAME in options else ""
