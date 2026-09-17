# Open Deck v0

The hand-wired prototype: breadboard, off-the-shelf parts, USB-tethered.
**Everything here is built and verified working on real hardware.** The
`FACE`/`LIST` wire protocol and the glance layer are new — built and covered
by the host-side test suite, but not yet re-verified against the physical
deck.

v1 will replace the breadboard with a custom PCB — see the root
[README](../README.md).

---

## Contents

```
v0/
├── BOM.md                  parts list, wiring, print notes
├── firmware/
│   ├── open_deck/          THE firmware - flash this
│   │                       (pixie_eyes.h is a vendored, patched RoboEyes)
│   └── diagnostics/        bring-up sketches (i2c scan, key probe, ...)
├── bridge/
│   ├── opendeck/           host bridge (stdlib only)
│   └── tests/              228 offline tests, no hardware needed
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

   > Build with the board's default USB mode (`hwcdc`). It uses the hardware
   > USB-Serial/JTAG peripheral, so the port exists whatever the firmware does
   > — a bad flash can always be recovered with another flash.
4. **Verify** the wiring before going further:
   ```bash
   arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 -p PORT firmware/diagnostics/i2c_scanner
   ```
   The OLED must appear at `0x3C`. If nothing shows up, it's the wiring or a
   charge-only USB cable — not the code.
5. **Run the bridge.** There is no install step — it is stdlib-only and runs
   on the Python macOS ships:
   ```bash
   ./open-deck --command grok
   ```

No hooks, no `settings.json` edits — everything is read from tmux. Run your
agents under `tmux` and the deck picks them up automatically.

6. **Optionally run it at login**:
   ```bash
   ./scripts/autostart install     # uninstall / status also work
   ```
   Installs a launchd agent that restarts on crash and logs to
   `~/Library/Logs/opendeck.log`. It copies the bridge to
   `~/Library/Application Support/OpenDeck` — macOS blocks launchd agents from
   reading `~/Documents`, so pointing one at a checkout there fails. Re-run
   after pulling.

Optional config at `~/.config/opendeck/config.json`:

```json
{
  "launch_command": "grok",
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
python3 tools/serial_mirror_gui.py
```

> The bridge itself needs nothing, but this tool is the exception: it needs
> `pyserial` and a real Tk. Apple's bundled Tcl/Tk 8.5.9 renders a blank
> window. `brew install python-tk@3.13`, `pip install pyserial`, and use that
> interpreter.

---

## Tests

```bash
bridge/tests/run_tests.sh
```

132 tests covering gesture timing, slot assignment, tmux actions, presence
resolution, pane-list formatting, config loading and event parsing. No
hardware or tmux required — everything is driven through fakes.

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
- **Scope input debouncing to the keys that need it.** A double-tap window
  held *every* tap for 350ms, though only one key had a double binding - so
  seven keys paid for a feature they never used. Latency you add deliberately
  is still latency.
- **A full OLED flush blocks for 29.5ms.** Sharing a thread with input means
  the encoder is never sampled during a flush, and detents get *dropped* —
  which reads as inconsistency, not lag. Rendering is pinned to core 0 and
  `loop()` owns core 1. Measured: 29,500µs blind window → 390µs.
- **Stay on the default `hwcdc` USB mode.** It was briefly built as
  `USBMode=default` (TinyUSB) to get HID, which cost three separate hazards:
  the port renamed between app and bootloader so uploads failed on the first
  pass, and a firmware that failed to bring up USB made its own port vanish.
  Under `hwcdc` the port is dedicated silicon and exists whatever the firmware
  does, so a bad flash is always recoverable with another flash.
- **A charge-only USB-C cable** will power the board and blink the charge LED
  while enumerating nothing. The LED tells you nothing about the data link.
- **A status display that lies is worse than none.** Without a host keepalive
  the deck happily showed a stale face forever. Any received command is a
  liveness tick; 5s of silence closes Pixie's eyes.
