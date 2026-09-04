# Open Deck

An open-source physical control surface for terminal AI coding agents.

Eight keys, a rotary encoder, and a small OLED that answers one question
without making you switch windows:

> **Which agent needs me, and what does it want?**

Built for [Claude Code](https://claude.com/claude-code) first, with Grok CLI
and OpenCode profiles included. Adding a harness is a JSON file, not a code
change.

---

## Why

Running several coding agents at once, the bottleneck isn't typing — it's
**attention**. An agent hits a permission prompt and blocks; you don't notice
for six minutes. Another finishes and sits idle awaiting review; you don't
notice at all. A third is confidently doing the wrong thing.

Your main screen can show this, but it competes with everything else for the
same visual space and window focus. A small dedicated always-on display
doesn't. That's the whole idea.

---

## What it does

**Dashboard** — one row per agent: status, elapsed time, and context usage.
Blocked agents invert and the screen flash-alerts.

```
OPEN DECK     1 PENDING
──────────────────────
>1 FOX   RUN     2m14s
 2 OWL   BLOCK
 3 CAT   DONE     c81%
 4 PNDA  idle
```

**Approve** — when an agent blocks on a permission prompt, the deck raises it
automatically. ENTER approves, X denies. Multiple requests queue.

```
! APPROVE? WEBAPP
Bash
rm -rf ./node_modules
&& npm cache clean    v
──────────────────────
SCROLL TO READ ALL
```

**Also**: Focus (per-agent detail), Palette (encoder-scrollable saved prompts
and slash commands), Ambient (dimmed idle screen; mono OLEDs burn in).

---

## Key map

Two layers — tap and hold (~400ms) — because the encoder has no push-switch.

| Key | Tap | Hold |
|---|---|---|
| **TERM** | Focus selected agent's terminal | New agent in a free slot |
| **ENTER** ✓ | Enter / approve | Cycle permission mode |
| **MIC** 🎙 | Toggle dictation | Hold-to-talk |
| **X** ✗ | Esc — deny prompt / interrupt | Esc Esc — rewind |
| **FOX OWL CAT PANDA** | Select + focus that agent | **Interrupt that agent in place** |

Two design notes worth knowing:

**ENTER and X are contextually correct for free.** In Claude Code, Enter both
submits and accepts a permission prompt; Esc both denies a prompt and
interrupts a running turn. One physical key, one semantic action, in every
state — no mode-tracking in the bridge.

**Hold-to-interrupt-a-specific-agent** is the sleeper feature. You see agent 3
going off the rails on the dashboard, hold its key, it stops. You never left
the window you were in.

---

## Architecture

```
┌──────────────┐  USB serial  ┌────────────────┐   tmux send-keys   ┌─────────┐
│  Open Deck    │─────────────▶│ opendeck-bridge │──────────────────▶│ agents  │
│  XIAO ESP32S3 │  EVT / HB    │  (host daemon)  │   / keystrokes    │ 1..4    │
│               │◀─────────────│                 │◀──────────────────│         │
└──────────────┘  SLOT/APPROVE└────────────────┘   lifecycle hooks  └─────────┘
```

The firmware knows nothing about any harness — it emits semantic events
(`EVT KEY_AGENT2 HOLD`) and renders whatever state the bridge pushes back
(`SLOT 1 OWL blocked 0 42`). All harness knowledge lives in the bridge's JSON
profiles, so a new harness never requires a reflash.

Status comes from **Claude Code's hooks system** — `Notification` means
blocked, `Stop` means done, `PreToolUse` says what it's doing. That's a
first-class mechanism, not screen-scraping. Harnesses without hooks fall back
to tmux pane scraping (brittle, and where per-harness maintenance lands).

Approvals are delivered with `tmux send-keys` where possible: it reaches the
right pane **without stealing focus** and needs no Accessibility permissions.

---

## Setup

### 1. Flash the firmware

```bash
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 sketches/open_deck
arduino-cli upload  --fqbn esp32:esp32:XIAO_ESP32S3 -p /dev/cu.usbmodemXXXX sketches/open_deck
```

### 2. Install the bridge

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/pip install pyserial
```

### 3. Wire up Claude Code hooks

Merge `bridge/hooks/settings-snippet.json` into `~/.claude/settings.json`,
replacing `HOOK_PATH` with the absolute path to
`bridge/hooks/opendeck-hook.sh`. Every hook is fire-and-forget with a 1s
timeout and always exits 0 — a stopped bridge can never block an agent.

### 4. Run

```bash
bridge/.venv/bin/python -m opendeck.bridge --profile claude-code
```

Then start agents as usual. `tmux` is recommended — it's how the bridge
targets panes without stealing focus.

---

## Safety

A one-press physical approve button for AI agent actions is the best feature
here and the most dangerous one. On a 21-character mono display,
`rm -rf ./build` and `rm -rf ~/` look nearly identical if you're half-looking.
So:

- **Long commands can't be approved until you've scrolled them.** Reading is
  enforced by the interaction, not by good intentions.
- **Destructive patterns** (`rm -rf`, `git push --force`, `sudo`,
  `curl | sh`, credential paths, `DROP TABLE`…) render inverted with `!` and
  require a **second ENTER press**.
- **"Approve and don't ask again" is hold-only**, never a tap.
- **No auto-approve on a timer.** Ever.
- The terminal prompt stays authoritative — the deck is a convenience over
  it, never a replacement.

---

## Hardware

| Part | Notes |
|---|---|
| Seeed XIAO ESP32S3 | Dual-core 240MHz, 8MB PSRAM. USB-tethered in v1 |
| 1.3" OLED, SH1106 | 128×64 mono, I2C @ 0x3C |
| EC11 rotary encoder | Rotation only — the push-switch on our module was dead |
| 8× mechanical switches | 2×4 matrix, rows D0/D1, cols D10/D9/D8/D7 |

Rows are driven `OUTPUT_OPEN_DRAIN` so two keys sharing a column across rows
can't short one row's output into the other. Only one key carries a diode
(a leftover from bring-up); the rest are switch-only, which is fine without
simultaneous-chord input.

**Known v1 gap:** the deck can't get your attention when you aren't looking at
it. A **piezo buzzer** would be worth more than every visual affordance in
this repo combined — put a footprint on the PCB even if you don't populate it.

---

## Repo layout

```
sketches/open_deck/       firmware (Arduino / ESP32)
bridge/opendeck/          bridge daemon
bridge/profiles/          per-harness JSON (claude-code, grok, opencode)
bridge/hooks/             Claude Code hook script + settings snippet
bridge/tests/             offline tests - no hardware needed
tools/serial_mirror_gui.py   mirrors the deck UI on your laptop for debugging
cad/                      keycap badge DXFs
docs/product-spec.md      the full design rationale
docs/protocol-spec.md     wire protocol
```

Tests: `bridge/.venv/bin/python -m unittest discover -s bridge/tests`

---

## Status

| Phase | Status |
|---|---|
| Hardware bring-up (display, encoder, 8-key matrix) | ✅ validated |
| Firmware: protocol + all display modes | ✅ built |
| Bridge daemon + hooks + profiles | ✅ built, 24 tests passing |
| Live end-to-end with real agents | ⏳ needs real-world use |
| Custom PCB + enclosure | 📋 designed, not fabricated |

MIT licensed. Not affiliated with Anthropic, xAI, or any harness vendor.
