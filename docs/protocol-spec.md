# Open Deck — Wire Protocol v2

USB CDC serial, 115200 baud, newline-delimited ASCII, bidirectional.

Human-readable on purpose: `screen /dev/cu.usbmodemXXXX 115200` is a complete
debugging setup.

---

## Device → host

```
EVT <KEY_NAME> DOWN|HOLD|UP
EVT ENCODER <+1|-1>
HB <uptime_ms>
```

### Keys

| Name | Position | Bound to |
|---|---|---|
| `KEY_TERM` | R1C1 | launch agent / split / new window |
| `KEY_MIC` | R1C2 | Space (voice toggle) |
| `KEY_AGENT1` | R1C3 | Fox |
| `KEY_AGENT4` | R1C4 | Panda |
| `KEY_ENTER` | R2C1 | Enter |
| `KEY_CANCEL` | R2C2 | interrupt / close pane |
| `KEY_AGENT3` | R2C3 | Cat |
| `KEY_AGENT2` | R2C4 | Owl |

`HOLD` fires at 400ms while a key is still down. The host runs the *hold*
action on `HOLD`, and the *tap* action on `UP` **only if no `HOLD` was seen**
since the matching `DOWN`. Double-tap is resolved host-side within a 350ms
window. One physical press yields exactly one action.

---

## Host → device

```
STATE <idle|working|attention|done|active|asleep>
TOAST <text>
```

`STATE` sets Pixie's expression. `TOAST` shows one line for 1.8s, replacing
the face, then the face resumes.

Toast **replaces** rather than overlays: RoboEyes' `drawEyes()` flushes the
framebuffer itself, so an overlay would need a second full-frame write every
frame. A toast is drawn and flushed once and then costs nothing.

---

## Hardware notes

Verified by pressing R1C1..R2C4 in sequence and reading back what the device
reported:

| | |
|---|---|
| Rows | `D0` (row 1), `D1` (row 2) |
| Cols | `D7 D8 D9 D10` — **left to right** |
| Display | SH1106 128×64, I2C `0x3C`, on `D4`/`D5` |
| Encoder | CLK `D3`, DT `D6`; push-switch dead/unused |

Column order is the reverse of what the wiring diagram suggests. It was
measured, not derived. Don't re-derive it.

---

## Three constraints the firmware is built around

**Rendering runs on the second core.** A full SH1106 flush blocks for
**29.5ms** (measured), and RoboEyes wants a frame every 20ms — so on one
thread the display saturates the loop and the encoder is never sampled during
a flush. Detents last a few milliseconds, so they were not arriving late, they
were being *dropped*. Rendering is pinned to core 0; `loop()` owns core 1 for
input alone. Measured effect: worst input blind window 29,500µs → 390µs, loop
rate 1,100/s → 3,704/s.

**Serial writes drop rather than block.** ESP32-S3 native USB CDC blocks once
its TX ring fills with no host reading. `emit()` checks
`Serial.availableForWrite()` first. An unguarded `Serial.printf` was measured
stalling the loop for 1.8s while no host was attached.

**Rows are `OUTPUT_OPEN_DRAIN`.** LOW sinks, HIGH releases rather than
sources, so two keys sharing a column across both rows cannot short one row's
output into the other.
