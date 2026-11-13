# Tracking PWM

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
2. Install `Tracking PWM`, restart Home Assistant.

### Manual

1. Copy `custom_components/tracking_pwm/` into your HA `custom_components/` folder.
2. Restart Home Assistant.

## Configuration (YAML)

```yaml
number:
  - platform: tracking_pwm
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

## Theory

The controller is a first-order error-feedback (sigma-delta / Bresenham)
modulator. Let `w ∈ [0,1]` be the wanted duty and `u ∈ {0,1}` the relay
state. Every evaluation integrates the delivery error:

```
debt += (u - w) * dt            # duty-seconds, + means over-delivered
relay = ON  iff  w > 0 and debt <= 0
```

**Exactness.** As long as the debt stays bounded, the long-run average is
exact by construction:

```
mean(u - w) = (debt(T) - debt(0)) / T  ->  0   as T -> infinity
```

Boundedness follows from the rule itself: the relay can only stay ON while
`debt <= 0` (each ON tick adds `(1-w)*dt > 0`) and only stay OFF while
`debt > 0` (each OFF tick subtracts `w*dt`), so the integrator is forced
to turn around within roughly one dwell of crossing zero. The clamp
(`max(8*dwell, 2*min_cycle, 600)` duty-seconds) is pure anti-windup for
pathological cases.

**Dwell and cycle period as minimum-pulse quantizers.** The dwell guard
(`minimal_switch_time`) forbids flips faster than the relay can follow;
the minimum cycle period forbids new cycles faster than its setting. Both
defer a switch, never cancel it — the debt keeps integrating the actual
output in the meantime and the flipped phase is stretched until the books
balance. Result: mid-range duties dither at the fastest allowed rate
(50% with 2min dwell = 2min ON / 2min OFF), while 5% becomes one 2min pulse
per ~40min. Same average, far less switching than a fixed grid.

**Limit cycles, not fixed cycles.** There is no cycle anchor: the period
emerges from the setpoint (U-shaped: ~4min at 50%, ~40min at 5% or 95%
with 2min dwell). This is the classic behavior of undithered first-order
sigma-delta modulators; here the dwell and debt shape it into
relay-friendly patterns instead of idle tones.

**Literature.** The modulator itself is textbook: a software first-order
sigma-delta is "increment a variable with the commanded number, then
subtract the number actually applied" ([Embedded, 2004][1]); the same
accumulator drives Bresenham line drawing and has long been used to dither
heaters ([EE StackExchange, 2014][2]). Limit-cycle/tonal behavior of
undithered first-order loops is analyzed in [Reiss & Sandler (2003)][3].
Minimum-pulse control of the same structure is even patented ([US7830289B2,
2010][4]) — our dwell + debt is that idea in software. The same short-pulse
problem appears in home-automation PWM: openHAB's PWM module debates duty
limits for burner protection ([openhab#12196][5]), Marlin weighed
sigma-delta heater PWM against MOSFET heating and AVR limits ([Marlin#12806][6]),
and HA PID thermostats visibly stretch pulses under `min_cycle_duration`
instead of repaying them. Cycle-anchored designs (ESPHome `slow_pwm`,
`HASmartThermostat`) quantize duty onto a fixed grid; this integration
replaces the grid with the error integral, so the average is exact at any
duty with any dwell.

[1]: https://www.embedded.com/sigma-delta-techniques-extend-dac-resolution/
[2]: https://electronics.stackexchange.com/questions/127064/what-are-some-problems-with-running-a-heating-element-in-pwm-mode
[3]: https://joshreiss.github.io/documents/2003/ReissSandler-2003-AES115.pdf
[4]: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7830289
[5]: https://github.com/openhab/openhab-addons/issues/12196
[6]: https://github.com/MarlinFirmware/Marlin/issues/12806

## Development

```bash
pip install -r requirements_test.txt
python -m pytest tests/
```

The control core (`controller.py`) has zero Home Assistant dependencies, so
the suite runs anywhere in milliseconds. The HA wrapper (`number.py`) is
intentionally thin: schema, duty normalization, service calls, restore.
