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
| `KEY_MIC` | R1C2 | voice toggle (Space; `C-Space` on grok) |
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
FACE <alert|busy|done|calm>
TOAST <text>
LIST <title>|<row>|<row>|...
PEEK <bar>|<headline>|<detail>
SLOTS <4 chars>
```

`FACE` sets Pixie's expression, one of four wire states. The old
`idle`/`working`/`attention`/`done`/`active`/`asleep` set is gone —
`idle`/`active` rendered identically and `asleep` was presentation rather
than a state of its own, so the daemon now resolves everything down to
`alert`, `busy`, `done`, or `calm` (see `presence.py`).

`TOAST` shows one line for 1.8s, replacing the face, then the face resumes.

`LIST` shows the pane list for whichever session the encoder or a project key
just brought into view — a title row plus up to five pane rows — held for
1.2s, then decaying back to the face. Summon sends `LIST` too, in place of a
toast, because naming the destination and showing its contents in one shot is
strictly more useful than a line of text.

`PEEK` carries three rows with fixed roles, because the device positions each
by role rather than stacking them: an inverted **bar** naming the key, a
**headline** the panel is built around, and a small **detail** line. The
headline is drawn at double size when it fits in 10 characters and normal size
otherwise, so a short session name reads across a desk and a long one still
reads at all.

`PEEK` shows what a held key will do, replacing everything else on screen. It
has no timeout: it goes up when the hold registers and comes down when the key
is released, so it tracks the finger. An empty payload clears it.

Peeking is non-destructive by design. Holding used to interrupt that slot's
session; a destructive action on the same gesture teaches people not to
explore, which defeats the point of a self-documenting device.

`SLOTS` carries one status character per key, in slot order — the 2×2 status
cluster drawn beside Pixie on the home screen. The cluster is 2×2 because the
animal keys are a 2×2 block; a left-to-right strip would map to nothing the
hand knows. It carries no labels: the keycaps already say which is which. It is the only message that describes all four
projects at once, and the only one that is permanently on screen rather than
decaying back to the face.

| Char | Meaning |
|---|---|
| (space) | no session yet — pressing the key creates one |
| `.` | idle: a shell, nothing running |
| `@` | working: something is running |
| `!` | needs you: a bell, or activity where you are not looking |

Sent only when it changes. The device redraws the strip from its own copy every
frame, so re-sending an identical line costs serial bandwidth that key events
need and buys nothing.

`LIST` travels as **one line**, never a begin/item/end sequence. A multi-line
render can be interrupted mid-draw by whatever the host sends next, leaving a
half-built screen on the panel; a single line either arrives complete or not
at all. The host does every formatting decision — windowing to five rows with
the active pane always kept visible, the `>` active marker, tmux window
flags, label truncation and delimiter sanitisation, all in `panes.py` — and
hands the firmware one `|`-delimited string. The firmware only splits on `|`
and draws each field verbatim; it makes no layout decisions of its own.

Toast and list both **replace** rather than overlay the face: RoboEyes'
`drawEyes()` flushes the framebuffer itself, so an overlay would need a
second full-frame write every frame. Each is drawn and flushed once and then
costs nothing until it expires.

---

## Liveness

The host sends `FACE <state>` every 2s regardless of whether the state
changed — a keepalive, not just a state push. The firmware treats **any**
received command as proof the host is alive; after 5s of silence it closes
Pixie's eyes and shows a `host offline` toast. This is deliberate: without a
keepalive the deck would happily keep showing a stale face forever after the
daemon died, and a status display that can go stale silently is worse than no
display. `lastHostCommand` is seeded at boot, so a deck powered on before the
daemon connects doesn't slam its eyes shut in the first few seconds.

An offline deck that stays offline blanks the panel entirely after 15
minutes, to avoid burning a static image into the mono OLED.

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
