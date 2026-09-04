# Open Deck

An open-source physical control surface for terminal AI coding agents.

Eight keys, a rotary encoder, and a small OLED that answer one question
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
same pixels and the same window focus. A small dedicated always-on display
doesn't. That's the whole idea.

---

## What it does

**Dashboard** — one row per agent: status, elapsed time, context usage.
Blocked agents invert and the screen flash-alerts.

```
OPEN DECK     1 PENDING
──────────────────────
>1 FOX   RUN     2m14s
 2 OWL   BLOCK
 3 CAT   DONE     c81%
 4 PNDA  idle
```

That `c81%` is context usage — the early warning that an agent is about to
compact and start forgetting your instructions. Invisible in normal use until
it bites you.

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

**Also**: Focus (per-agent detail), Palette (encoder-scrollable saved prompts),
Ambient (dimmed idle screen — mono OLEDs burn in).

---

## Key map

Two layers, tap and hold (~400ms), because the encoder has no push-switch.

```
 TERM   MIC    FOX    PANDA
 ENTER   X     CAT    OWL
```

| Key | Tap | Hold |
|---|---|---|
| **TERM** | Focus selected agent's terminal | New agent in a free slot |
| **ENTER** ✓ | Enter / approve | Cycle permission mode |
| **MIC** 🎙 | Toggle dictation | Hold-to-talk |
| **X** ✗ | Esc — deny / interrupt | Esc Esc — rewind |
| **FOX OWL CAT PANDA** | Select + focus that agent | **Interrupt that agent in place** |

**ENTER and X are contextually correct for free.** In Claude Code, Enter both
submits and accepts a permission prompt; Esc both denies a prompt and
interrupts a running turn. One physical key, one semantic action, in every
state — no mode-tracking in the bridge.

**Hold-to-interrupt-a-specific-agent** is the sleeper feature. You watch agent
3 go off the rails on the dashboard, hold its key, it stops. You never left the
window you were in.

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
blocked, `Stop` means done, `PreToolUse` says what it's doing. First-class
mechanism, not screen-scraping. Harnesses without hooks fall back to tmux pane
scraping (brittle, and where per-harness maintenance lands).

Approvals are delivered with `tmux send-keys` where possible: it reaches the
right pane **without stealing focus** and needs no Accessibility permissions.

---

## Versions

| | |
|---|---|
| **[v0](v0/)** | Hand-wired breadboard prototype. USB-tethered, off-the-shelf parts. **Built and working.** Start here |
| **v1** | Custom PCB with the XIAO reflow-mounted via castellated pads, proper diode matrix, piezo buzzer. Not started |

Start with [`v0/README.md`](v0/README.md) and [`v0/BOM.md`](v0/BOM.md).

---

## Safety

A one-press physical approve button for AI agent actions is the best feature
here and the most dangerous one. On a 21-character mono display,
`rm -rf ./build` and `rm -rf ~/` look nearly identical if you're half-looking.
So:

- **Long commands can't be approved until you've scrolled them.** Reading is
  enforced by the interaction, not by good intentions.
- **Destructive patterns** (`rm -rf`, `git push --force`, `sudo`, `curl | sh`,
  credential paths, `DROP TABLE`…) render inverted with `!` and require a
  **second ENTER press**.
- **No auto-approve on a timer.** Ever.
- The terminal prompt stays authoritative — the deck is a convenience over it,
  never a replacement.

The gate is enforced in **firmware**, by withholding the serial event — not
just by refusing to advance the display. The host acts on any `KEY_ENTER` it
receives, so a display-only guard would be decorative. (It was, briefly. That
bug is why this section is specific.)

---

## Status

| | |
|---|---|
| Hardware bring-up (display, encoder, 8-key matrix) | ✅ validated |
| Firmware: protocol + all display modes | ✅ built |
| Bridge daemon + hooks + profiles | ✅ built, 27 tests passing |
| Full chain: key → firmware gate → serial → bridge → tmux → agent | ✅ verified on hardware |
| Grok / OpenCode profiles | ⏳ written, never run against those harnesses |
| Long-run use with real agents | ⏳ the only test that matters, not done yet |
| Custom PCB | 📋 v1 |

### Known gap

The deck can't get your attention when you aren't looking at it. A flashing
screen in your peripheral vision is a weak signal, and the whole premise is
that you're *not* watching it until it has something to say.

**A piezo buzzer would be worth more than every visual affordance in this
repo.** v1 should populate one.

---

MIT licensed. Not affiliated with Anthropic, xAI, or any harness vendor.
