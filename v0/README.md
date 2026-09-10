# Open Deck v0

The hand-wired prototype: breadboard, off-the-shelf parts, USB-tethered.
**Everything here is built and verified working on real hardware.**

v1 will replace the breadboard with a custom PCB — see the root
[README](../README.md).

---

## Contents

```
v0/
├── BOM.md                  parts list, wiring, print notes
├── firmware/
│   ├── open_deck/          THE firmware - flash this
│   └── diagnostics/        bring-up sketches (i2c scan, key probe, ...)
├── bridge/
│   ├── opendeck/           host daemon
│   ├── profiles/           per-harness JSON (claude-code, grok, opencode)
│   └── tests/              95 offline tests, no hardware needed
├── cad/
│   ├── stl/                printable shells + 8 keycaps
│   └── dxf/                badge icon outlines (for remixing keycaps)
└── tools/
    └── serial_mirror_gui.py   mirrors the deck UI on your laptop
```

---

## Build order

1. **Print** the shells and keycaps — `cad/stl/`, see [BOM.md](BOM.md)
2. **Wire** it up — pin map in [BOM.md](BOM.md)
3. **Flash** the firmware:
   ```bash
   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 firmware/open_deck
   arduino-cli upload  --fqbn esp32:esp32:XIAO_ESP32S3 -p /dev/cu.usbmodemXXXX firmware/open_deck
   ```
4. **Verify** the wiring before going further:
   ```bash
   arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 -p PORT firmware/diagnostics/i2c_scanner
   ```
   The OLED must appear at `0x3C`. If nothing shows up, it's the wiring or a
   charge-only USB cable — not the code.
5. **Install the daemon** (Python 3.11+):
   ```bash
   python3 -m venv .venv && .venv/bin/pip install pyserial
   ```
6. **Run**:
   ```bash
   cd bridge && ../.venv/bin/python -m opendeck --command cla
   ```

No hooks, no `settings.json` edits — everything is read from tmux. Run your
agents under `tmux` and the deck picks them up automatically.

7. **Optionally run it at login**:
   ```bash
   ./scripts/install-service.sh cla
   ```
   Installs a launchd agent that restarts on crash. Logs to
   `~/Library/Logs/opendeck.log`; the script prints the stop/uninstall
   commands.

Optional config at `~/.config/opendeck/config.json`:

```json
{
  "launch_command": "cla",
  "sessions": ["webapp", "api", null, null],
  "encoder_scope": "session"
}
```

---

## Diagnostics

If something misbehaves, these isolate it faster than guessing:

| Sketch | Answers |
|---|---|
| `i2c_scanner` | Is the display on the bus at all? |
| `raw_io_test` | Live pin states — is a key or the encoder actually wired? |
| `key_test` | Single-key press detection |
| `encoder_menu_test` | Encoder rotation with the debounced lookup-table decoder |
| `open_deck_validate` | Display + encoder + one key together |
| `open_deck_matrix` | Full 8-key matrix with an on-screen grid |
| `pixie_face_test` | Pixie cycling every emotion, standalone |

`tools/serial_mirror_gui.py` renders the deck's UI on your laptop from the
same serial stream — useful for telling "the display is slow" apart from
"the firmware is slow".

```bash
../.venv/bin/python tools/serial_mirror_gui.py
```

> On macOS this needs a real Tk. Apple's bundled Tcl/Tk 8.5.9 renders a blank
> window. `brew install python-tk@3.13` and use that interpreter.

---

## Tests

```bash
bridge/tests/run_tests.sh
```

95 tests covering gesture timing, slot assignment, tmux actions, presence
resolution, config loading and event parsing. No hardware or tmux required —
everything is driven through fakes.

---

## Hard-won notes

Things that cost real debugging time, so you don't repeat them:

- **The display is SH1106, not SSD1306.** An SSD1306 driver renders
  plausible-looking garbage rather than failing cleanly.
- **Column order is `D7 D8 D9 D10` left to right** — the reverse of what the
  wiring notes implied. It was determined by pressing keys and reading back
  what the device reported. Measure, don't derive.
- **Serial writes must not block.** ESP32-S3 native USB CDC blocks once its TX
  ring fills with no host reading. Inline `Serial.print` in the main loop then
  stalls the key scan *and* the display. The firmware drops lines instead.
- **Don't redraw the OLED on a timer.** A full-frame I2C push is ~30ms; doing
  it 30×/second regardless of activity starves everything else. Redraw on
  change only.
- **`pinMode()` is expensive on ESP32.** Toggling rows between `OUTPUT` and
  `INPUT` every scan was slow enough to make the encoder feel laggy;
  `OUTPUT_OPEN_DRAIN` set once gives the same protection for free.
- **A full OLED flush blocks for 29.5ms.** Sharing a thread with input means
  the encoder is never sampled during a flush, and detents get *dropped* —
  which reads as inconsistency, not lag. Rendering is pinned to core 0 and
  `loop()` owns core 1. Measured: 29,500µs blind window → 390µs.
- **A charge-only USB-C cable** will power the board and blink the charge LED
  while enumerating nothing. The LED tells you nothing about the data link.
