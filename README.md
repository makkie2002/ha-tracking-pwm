# Slow PWM

A Home Assistant number entity that drives a **single relay** from an analog
setpoint using sigma-delta (Bresenham-style) error feedback.

Each evaluation integrates the delivery error:

```
debt += (actual - wanted) * dt
```

The relay is ON whenever heat is owed (`debt <= 0` and wanted > 0) and OFF
whenever over-delivery is unpaid (`debt > 0`). Two guards keep it
relay-friendly:

* **Dwell** (`minimal_switch_time`, default 2min): the relay never flips
  faster than this, in either direction.
* **Minimum cycle period** (`minimal_cycle_period`, default 2× dwell):
  minimum time between cycle starts (OFF→ON). Caps the switching rate;
  stretches the long phase of each cycle.

The debt repays forced pulses exactly, so the **long-term average equals
the wanted duty at any setpoint** — there is no deadband error and no
cycle anchor to fall behind. At 50% with defaults the relay runs a
2min ON / 2min OFF metronome; at 5% it fires one 2min pulse per ~40min.

The number state always shows the wanted value; the `delivery_debt`
attribute (duty-seconds, + means over-delivered) shows the integrator state
and `output_states` the relay.

## Installation

### HACS (preferred)

1. In HACS, add this repository as a custom integration repository.
2. Install `Slow PWM`, restart Home Assistant.

### Manual

1. Copy `custom_components/slow_pwm/` into your HA `custom_components/` folder.
2. Restart Home Assistant.

## Configuration (YAML)

```yaml
number:
  - platform: slow_pwm
    name: Floorheater living room
    outputs:
      - "switch.living_room_group1"
    minimum: 0
    maximum: 100
    minimal_switch_time: {'minutes': 2, 'seconds': 0}
    minimal_cycle_period: {'minutes': 10, 'seconds': 0}  # optional, default 2x dwell
    update_interval: {'seconds': 30}
    step: 1
    mode: "auto"
    unique_id: "floorheater_pwm"
```

| Parameter | Required | Default | Meaning |
|---|---|---|---|
| `name` | yes | — | Entity name |
| `outputs` | yes | — | Exactly one switch `entity_id` (list with one entry) |
| `minimum` / `maximum` | no | 0 / 100 | Values meaning fully off / fully on |
| `minimal_switch_time` | no | 2min | Minimum relay on/off time (dwell, both directions) |
| `minimal_cycle_period` | no | 2× dwell | Minimum time between cycle starts |
| `update_interval` | no | 30s | Re-evaluation tick; keeps the average exact with no new writes |
| `step` / `mode` / `unique_id` | no | 1 / slider | Standard number entity options |

Writes (`number.set_value`, e.g. from a PID controller every 30s) are
evaluated immediately; the periodic tick keeps the dither going when the
PID is quiet. Service calls fire only on actual relay flips.

## Development

```bash
pip install -r requirements_test.txt
python -m pytest tests/
```

The control core (`controller.py`) has zero Home Assistant dependencies, so
the suite runs anywhere in milliseconds. The HA wrapper (`number.py`) is
intentionally thin: schema, duty normalization, service calls, restore.
