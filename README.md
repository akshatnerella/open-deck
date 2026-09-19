# Open Deck

An open-source physical control surface for terminal AI coding agents.

Four project keys, a tuning dial, and a small face that tells you what your
agents are up to.

Built around **tmux**: the four animal keys are four tmux sessions, the encoder
steps through the panes inside one. Harness-agnostic — it works with Claude
Code, Grok CLI, OpenCode, or a plain shell, because it reads tmux rather than
integrating with any of them.

---

## Key map

```
 TERM   MIC    FOX    PNDA
 ENTER   X     CAT    OWL
```

| Key | Tap | Double-tap | Hold |
|---|---|---|---|
| **FOX OWL CAT PNDA** | go to that session — creates it if new | | list its panes |
| **TERM** | start the agent in this pane | new pane beside | new window |
| **X** | interrupt — `C-c` in a shell, `Escape` in an agent | close the pane | |
| **ENTER** | Enter — or go to the highlighted pane | | |
| **Encoder** | move through panes | | |

**One chord:** hold **ENTER** and double-tap **TERM** to split *below* instead
of beside.

Three behaviours worth knowing:

**ENTER, X and MIC change meaning with the pane.** `C-c` interrupts a shell but
`Escape` interrupts an agent without killing it; voice is `Space` in Claude and
`Ctrl-Space` in grok. In a plain shell MIC sends nothing at all — there's no
voice mode to toggle, and a stray space would type one.

**Starting an agent somewhere new is two presses:** double-tap TERM for an
empty pane, then tap TERM to fill it. One key never rearranges your screen as a
side effect of launching something.

**Tap X to stop it, double-tap X to close it.** Closing runs `exit`, so the
shell cleans up and tmux ends the session if it was the last pane. It refuses
while a program is running and toasts `still running` — tapping X already
interrupts, so the sequence is tap then double-tap.

---

## Setting it up on a Mac

Nothing to install for the host side: the bridge is **stdlib-only** and runs on
the Python that ships with macOS.

```bash
git clone git@github.com:akshatnerella/open-deck.git
cd open-deck
./open-deck                    # that's the whole install
```

You need **tmux** (`brew install tmux`) and an agent CLI on your `PATH`.

To have it start at login:

```bash
./scripts/autostart install    # uninstall / status also work
```

This copies the bridge to `~/Library/Application Support/OpenDeck` rather than
pointing at your checkout, because macOS blocks launchd agents from reading
`~/Documents`. Re-run it after pulling. Logs go to `~/Library/Logs/opendeck.log`.

### Flashing the deck

Only needed on a new board, not on a new Mac — the firmware lives on the
device.

```bash
arduino-cli core install esp32:esp32 \
  --additional-urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli lib install "Adafruit GFX Library" "Adafruit SH110X"

arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 v0/firmware/open_deck
arduino-cli upload  --fqbn esp32:esp32:XIAO_ESP32S3 -p /dev/cu.usbmodemXXXX v0/firmware/open_deck
```

The eye renderer is vendored as `pixie_eyes.h`, so there's no third library to
install. See the notes at the top of that file for what's patched and why.

> **Using the Arduino IDE instead?** It keeps a *separate* config from
> `arduino-cli` — same sketchbook, different board packages. Add the Espressif
> URL under **Settings → Additional boards manager URLs**, then quit and reopen
> the IDE, or the board won't appear even though it's installed.

> **Only one thing can hold the serial port.** Close the IDE's Serial Monitor
> before running the bridge, and stop the bridge before flashing.

### Configuration

None required. The four keys already mean `fox`, `owl`, `cat`, `pnda`.

Optional, at `~/.config/opendeck/config.json`:

```json
{
  "harness": "grok",
  "sessions": ["webapp", "api", null, null]
}
```

`harness` is one of `claude`, `grok`, `opencode`, `codex`, `aider` — it picks
the launch command and the right keystrokes for ENTER, X and MIC. Detection
stays permissive: a deck set to grok still shows a Claude pane as working,
because the setting decides what a key *launches* and must not make the display
lie about what's running.

---

## What it does

**A key means the same session every time.** FOX is `fox`, CAT is `cat`. If it
doesn't exist yet, pressing the key creates it. Nothing is discovered, nothing
gets reshuffled — a physical button whose meaning moves is worse than no button.

**Hold a key to see inside.** The panel lists that session's panes: a mark for
shell or agent, the active one flagged, and whatever each pane is best called.
Claude Code reports a session title (`open deck`), which beats anything the deck
could infer. A plain terminal shows as `zsh` rather than being hidden.

**The dial browses.** In the session you're in it follows along — your Mac is
the preview. Hold an animal and it browses *that* session without moving you; a
dial shouldn't yank you out of what you're reading. ENTER goes to the
highlighted pane, switching sessions if it's elsewhere. Stop touching it and the
list gives up after a couple of seconds and goes back to Pixie. It's a
look-and-go tool, not a mode.

**The home screen is Pixie, and only Pixie.** She has the whole panel. Her
expression is driven by tmux state — concerned when something wants attention in
a session you aren't watching, happy when an agent finishes, curious while one
works.

**A live deck never lies about being live.** The bridge pings the display every
couple of seconds; if that stops, Pixie's eyes close and a `host offline` toast
appears within about five seconds, rather than leaving a stale face on screen.

### Attention

When a session you aren't looking at rings a bell or shows activity, the deck
inverts the whole screen three times, Pixie turns to a scowl, and a toast names
the session (`OWL wants you`). A standing alert re-pulses every 10s.

`invertDisplay()` is a single command byte rather than a framebuffer write, so
flashing is effectively free next to the ~29.5ms cost of a redraw.

A piezo buzzer would still beat any visual signal for catching attention when
you're looking elsewhere entirely — v1's PCB should populate one.

---

## Architecture

```
┌───────────────┐  USB serial  ┌─────────────────┐    tmux     ┌──────────┐
│   Open Deck   │─────────────▶│    opendeck     │────────────▶│ sessions │
│ XIAO ESP32S3  │  EVT / HB    │  (host bridge)  │  + Ghostty  │  panes   │
│               │◀─────────────│                 │◀────────────│  agents  │
└───────────────┘ FACE/TOAST/  └─────────────────┘   polling   └──────────┘
                  PEEK/LIST
```

The firmware knows nothing about tmux or any harness — it emits semantic events
(`EVT KEY_AGENT2 HOLD`) and renders whatever the host pushes back. All the
knowledge lives in the bridge, where it's testable without hardware.

**Everything is derived from tmux**, which already tracks per-window activity
and bell flags — the "something happened where you aren't looking" signal, free,
for every harness. No hooks, no `settings.json` edits, no screen scraping.

Keys reach panes with `tmux send-keys`: it hits the right pane **without
stealing focus** and needs no macOS Accessibility permission. The deck is
deliberately **not** a USB keyboard — see
[docs/decisions/no-hid.md](docs/decisions/no-hid.md) for why that was built
twice and removed twice.

---

## Versions

| | |
|---|---|
| **[v0](v0/)** | Hand-wired breadboard prototype. USB-tethered, off-the-shelf parts. **Built and working.** Start here |
| **v1** | Custom PCB with the XIAO reflow-mounted via castellated pads, proper diode matrix, piezo buzzer. Not started |

See [`v0/README.md`](v0/README.md) and [`v0/BOM.md`](v0/BOM.md).

---

## Status

| | |
|---|---|
| Hardware: display, encoder, 8-key matrix | ✅ validated |
| Firmware: input on core 1, rendering on core 0 | ✅ built |
| Host bridge: tmux navigation, peek, Pixie | ✅ built, 211 tests |
| Claude Code and Grok CLI | ✅ detection and keymaps measured on both |
| OpenCode / Codex / Aider | ⏳ patterns written, unverified against those CLIs |
| Custom PCB | 📋 v1 |

Tests run on stock macOS Python with no dependencies:

```bash
cd v0/bridge && python3 -m unittest discover -s tests
```

---

MIT licensed. Not affiliated with Anthropic, xAI, or any harness vendor.
