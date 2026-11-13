"""Constants for the Slow PWM integration."""

DOMAIN = "slow_pwm"

CONF_OUTPUTS = "outputs"
CONF_MIN_SWITCH_TIME = "minimal_switch_time"
CONF_MIN_CYCLE_PERIOD = "minimal_cycle_period"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_STEP = "step"

ATTR_OUTPUT_STATES = "output_states"
ATTR_DELIVERY_DEBT = "delivery_debt"
ATTR_MIN_SWITCH_TIME = "minimal_switch_time"
ATTR_MIN_CYCLE_PERIOD = "minimal_cycle_period"
ATTR_UPDATE_INTERVAL = "update_interval"

MODE_SLIDER = "slider"
MODE_BOX = "box"
MODE_AUTO = "auto"

DEFAULT_MODE = MODE_SLIDER
DEFAULT_SWITCH_TIME = {"minutes": 2}
DEFAULT_UPDATE_INTERVAL = {"seconds": 30}
