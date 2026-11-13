"""Constants for the Slow PWM integration."""

DOMAIN = "tracking_pwm"

CONF_OUTPUTS = "outputs"
CONF_MIN_SWITCH_TIME = "minimal_switch_time"
CONF_MIN_CYCLE_PERIOD = "minimal_cycle_period"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_STEP = "step"

ATTR_OUTPUT_STATES = "output_states"
ATTR_DELIVERY_DEBT = "delivery_debt"
ATTR_WANTED_DUTY = "wanted_duty"
ATTR_SECONDS_SINCE_SWITCH = "seconds_since_switch"
ATTR_DWELL_REMAINING = "dwell_remaining"
ATTR_CYCLE_REMAINING = "cycle_remaining"
ATTR_LAST_ON_DURATION = "last_on_duration"
ATTR_LAST_OFF_DURATION = "last_off_duration"
ATTR_SWITCH_COUNT = "switch_count"
ATTR_MIN_SWITCH_TIME = "minimal_switch_time"
ATTR_MIN_CYCLE_PERIOD = "minimal_cycle_period"
ATTR_UPDATE_INTERVAL = "update_interval"

MODE_SLIDER = "slider"
MODE_BOX = "box"
MODE_AUTO = "auto"

DEFAULT_MODE = MODE_SLIDER
DEFAULT_SWITCH_TIME = {"minutes": 2}
DEFAULT_UPDATE_INTERVAL = {"seconds": 30}
