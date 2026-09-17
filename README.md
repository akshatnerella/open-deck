# Open Deck

An open-source physical control surface for terminal AI coding agents.

Four project keys, a tuning dial, and a small face that tells you what your
agents are up to.

Built around **tmux**: the four animal keys are four tmux sessions, the encoder
steps through the panes inside one. Harness-agnostic — it works with Claude
Code, Grok CLI, OpenCode, or a plain shell, because it reads tmux rather than
integrating with any of them.

---

## Why

Running several coding agents at once, the bottleneck isn't typing — it's
**context switching**. Which project was that in? Which pane is the agent in?
Did the tests finish?

A dedicated key per project, hit without looking, beats hunting for a window.
And a small always-on face can show you what's happening in the sessions you
*aren't* looking at — something your main screen structurally can't, because it
only shows the thing in front.

---

## What it does

**Four keys, four tmux sessions.** Press an animal and that project comes to
the front, fullscreen, in your terminal. The previous session is detached, not
killed — everything keeps running.

A key means the same session every time: FOX is `fox`, CAT is `cat`. If it
doesn't exist yet, pressing the key creates it. Nothing is discovered, nothing
gets reshuffled, and there is nothing to configure before the deck is useful —
a physical button whose meaning moves is worse than no button at all.

**Encoder steps through the panes** in whichever session you're in. Splits and
separate windows alike; a terminal is a terminal.

**The strip shows all four at a glance.** A row under Pixie carries one mark
per key, so you can read the whole fleet from across a desk without focusing
your eyes:

| Mark | Meaning |
|---|---|
| (blank) | no session yet |
| `·` | idle — a shell, nothing running |
| `▮` | working — something is running |
| `!` | needs you — a bell, or activity where you aren't looking |

Pixie's face is the same information at lower resolution: she tells you
*whether* anything wants you, the strip tells you *which*.

**Hold any key to see what it does.** The panel shows the key, the state of
its session, and what tap does — so there is nothing to memorise and no manual
to lose. Holding changes nothing; that is what makes it safe to explore.

**Pixie reacts.** The face is driven by tmux state — she looks concerned when
something wants attention in a session you aren't watching, happy when an
agent finishes, curious while one works. Brief text toasts narrate what a
keypress did.

**Turning the dial, or pressing a project key, glances at that session.** The
face gives way to a pane list — title, position, up to five rows with the
active one always in view — for about a second, then decays back to Pixie.
Summon shows the list too, in place of a toast, because naming the
destination and showing its contents in one shot beats a line of text.

**A live deck never lies about being live.** The daemon pings the display
every couple of seconds; if that stops, Pixie's eyes close and a `host
offline` toast appears within about five seconds, rather than leaving a
stale face on screen.

---

## Running it

The deck talks to a small host bridge over USB serial. The bridge has **no
dependencies** — stdlib only, and it runs on the Python that ships with macOS:

```bash
./open-deck                  # that is the whole install
./scripts/autostart install  # or have it start at login
```

**The deck is not a keyboard and never types.** It sends events; the bridge
decides what they mean and drives tmux with `send-keys`, which names the pane
it is talking to. A keyboard cannot do that — it can only type into whatever
happens to have focus. That difference is the product, so it is worth being
plain about the trade: the deck does nothing at all until the bridge is
running. See [docs/decisions/no-hid.md](docs/decisions/no-hid.md).

---

## Key map

```
 TERM   MIC    FOX    PANDA
 ENTER   X     CAT    OWL
```

| Key | Tap | Double-tap | Hold |
|---|---|---|---|
| **TERM** | launch the agent here | launch in a split | new window |
| **MIC** | voice-mode toggle — Space, or `C-Space` on grok | | |
| **X** | interrupt, or close an idle pane | | |
| **ENTER** | Enter | | |
| **FOX OWL CAT PANDA** | summon that session fullscreen | | peek: what this key does |
| **Encoder** | step through panes in the current session | | |

**No configuration is required.** The four keys already mean `fox`, `owl`,
`cat`, `pnda`. If you want a key to mean a project of your own, name it in
`~/.config/opendeck/config.json` under `sessions` — but the binding stays
fixed either way. Bindings are resolved by name from a registry, so remapping
is config, not code.

Two behaviours worth knowing:

**X is context-aware.** Something running → `C-c`. Idle shell → types `exit`,
closing the pane. (`exit` on a session's last pane ends the session; its key
then makes a fresh one on next press.)

**TERM won't type into a busy pane.** If the pane is running vim or a build, it
refuses rather than injecting a command into it. Double-tap splits instead —
a fresh pane is always safe.

---

## Architecture

```
┌──────────────┐  USB serial  ┌────────────────┐    tmux     ┌──────────┐
│  Open Deck    │─────────────▶│    opendeck     │────────────▶│ sessions │
│  XIAO ESP32S3 │  EVT / HB    │  (host daemon)  │  + Ghostty  │  panes   │
│               │◀─────────────│                 │◀────────────│  agents  │
└──────────────┘ FACE/TOAST/LIST └────────────────┘   polling   └──────────┘
```

The firmware knows nothing about tmux or any harness — it emits semantic events
(`EVT KEY_AGENT2 HOLD`) and renders whatever the host pushes back
(`FACE busy`, a `TOAST`, or a `LIST` of panes). All the knowledge lives in the
daemon.

**Everything is derived from tmux**, which already tracks per-window activity
and bell flags — the "something happened where you aren't looking" signal, free,
for every harness. No hooks, no `settings.json` edits, no screen scraping.

Keys reach panes with `tmux send-keys`: it hits the right pane **without
stealing focus** and needs no macOS Accessibility permission.

---

## Versions

| | |
|---|---|
| **[v0](v0/)** | Hand-wired breadboard prototype. USB-tethered, off-the-shelf parts. **Built and working.** Start here |
| **v1** | Custom PCB with the XIAO reflow-mounted via castellated pads, proper diode matrix, piezo buzzer. Not started |

Start with [`v0/README.md`](v0/README.md) and [`v0/BOM.md`](v0/BOM.md).

---

## Status

| | |
|---|---|
| Hardware: display, encoder, 8-key matrix | ✅ validated |
| Firmware: input on core 1, rendering on core 0 | ✅ built |
| Host daemon: tmux navigation + Pixie | ✅ built, 179 tests |
| `FACE`/`LIST` protocol, glance layer, offline watchdog | ✅ built, 134 tests, verified on hardware |
| Grok / OpenCode profiles | ⏳ written, unverified against those harnesses |
| Custom PCB | 📋 v1 |

### Attention

When a session you aren't looking at rings a bell or shows activity, the deck
inverts the whole screen three times, Pixie turns to a scowl, and a toast names
the session (`OWL wants you`). A standing alert re-pulses every 10s.

`invertDisplay()` is a single command byte rather than a framebuffer write, so
flashing is effectively free next to the ~29.5ms cost of a redraw.

A piezo buzzer would still beat any visual signal for catching attention when
you're looking elsewhere entirely — v1's PCB should populate one.

---

MIT licensed. Not affiliated with Anthropic, xAI, or any harness vendor.
