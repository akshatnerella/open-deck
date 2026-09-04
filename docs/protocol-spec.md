# Open Deck — Wire Protocol v1.0

USB CDC serial, 115200 baud, newline-delimited ASCII, bidirectional.

Deliberately human-readable: you can `screen /dev/cu.usbmodemXXXX 115200`
and debug the whole thing by eye, which is how most of this was built.

**Status: implemented and verified on hardware.**

---

## Device → host

```
EVT <KEY_NAME> DOWN|HOLD|UP
EVT ENCODER <+1|-1>
HB <uptime_ms>
```

### Key names

| Name | Physical position | Function |
|---|---|---|
| `KEY_TERM` | R1C1 | Terminal / new session |
| `KEY_MIC` | R1C2 | Voice |
| `KEY_AGENT1` | R1C3 | Fox |
| `KEY_AGENT4` | R1C4 | Panda |
| `KEY_ENTER` | R2C1 | Confirm / approve |
| `KEY_CANCEL` | R2C2 | Deny / interrupt |
| `KEY_AGENT3` | R2C3 | Cat |
| `KEY_AGENT2` | R2C4 | Owl |

### Tap vs. hold

`HOLD` fires at 400ms while a key is still down. The host runs the *hold*
action on `HOLD`, and the *tap* action on `UP` **only if no `HOLD` was seen**
since the matching `DOWN`. One physical press therefore produces exactly one
action.

### Suppressed events

In approve mode the device **withholds** `KEY_ENTER` entirely (DOWN, HOLD and
UP) until the request is armed — i.e. the command has been scrolled to the end,
and confirmed a second time if it matched a destructive pattern.

This is a real gate, not a display convention: the host acts on any
`EVT KEY_ENTER` it receives, so emitting one early would approve the command
regardless and reduce the on-device guard to decoration. `KEY_CANCEL` is never
gated — deny must always work instantly.

---

## Host → device

```
SLOT <0-3> <name> <idle|run|blocked|done|error> <elapsed_s> <ctx_pct>
APPROVE <agent> <0|1 danger> <tool> <text...>
APPROVE_COUNT <n>
APPROVE_CLEAR
PALETTE_CLEAR
PALETTE_ADD <text...>
FOCUS_LINE <0-3> <text...>
MODE <DASHBOARD|APPROVE|PALETTE|FOCUS|AMBIENT>
ALERT
```

Semantic, not pixels. The device owns rendering — pushing a 1KB framebuffer
over a bus that already takes ~30ms per full-frame I2C write would be both
slow and pointless.

### Two rules the host must follow

**1. Re-pushing an identical `APPROVE` is a no-op — rely on it.**
The device compares agent+tool+text and ignores an exact repeat. Without this,
the host's periodic refresh would restart the alert blink forever *and* reset
the user's scroll position twice a second, making a long command impossible to
ever scroll through and arm.

**2. Queue depth goes in `APPROVE_COUNT`, never folded into `APPROVE`.**
It changes whenever another agent blocks. Baking it into the agent label
(`WEBAPP` → `WEBAPP(2)`) makes the request look new, defeating rule 1 and
resetting the scroll of the request being read right now.

Both were live bugs found on hardware, not hypotheticals.

---

## Hardware notes

Verified empirically by pressing R1C1..R2C4 in sequence and reading back what
the device reported:

| | |
|---|---|
| Rows | `D0` (row 1), `D1` (row 2) |
| Cols | `D7 D8 D9 D10` — **left to right** |
| Display | SH1106 128×64, I2C `0x3C`, on `D4`/`D5` |
| Encoder | CLK `D3`, DT `D6`; push-switch dead/unused |

Column order is the reverse of what the schematic labelling suggests. Don't
re-derive it from the wiring diagram — it was measured.

Rows are driven `OUTPUT_OPEN_DRAIN`: LOW sinks, HIGH releases rather than
sources, so two keys sharing a column across both rows cannot short one row's
output into the other.

Serial writes use `Serial.availableForWrite()` and **drop** rather than block.
ESP32-S3 native USB CDC blocks once its TX ring fills with no host reading,
and these writes sit inline in the main loop — a blocked write stalls the key
scan and the display along with it.
