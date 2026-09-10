# Open Deck × Pixie — Display Design

**Status:** approved, not yet implemented
**Date:** 2026-09-09

Wires [Pixie](https://github.com/akshatnerella/pixie) into Open Deck as the
device's interface layer rather than as decoration, and makes the OLED
genuinely useful without turning it into a dashboard.

---

## Goals

1. The display is informative when you need it and calm when you don't.
2. Every state is unmistakable at a glance on a 128×64 mono panel.
3. The display never lies about whether it is live.
4. No new hardware, no new dependencies, no new keys.

## Non-goals

- Menus or configuration on the device
- Per-pane detail views (the terminal already is one)
- Sound
- Any second screen or mode the user can get stuck in

---

## Model: three layers, separated by time

A 128×64 mono display can be a character or a dashboard. Splitting the screen
between them does both badly. Splitting by *time* does not.

| Layer | Trigger | Decay |
|---|---|---|
| **Ambient** | default | — (resting state) |
| **Glance** | encoder turn, session summon | 1.2s after last interaction |
| **Alert** | attention state entered | 1.8s toast, face persists |

The device owns all decay timing. The host says *what* to show, never for how
long. This keeps timing behaviour in one place and makes the host stateless
with respect to the display.

---

## Face states

Four semantic states. The previous six included `idle` and `active`, which
rendered identically — two states that look the same are one state — and
`asleep`, which is a presentation concern rather than a meaning.

| Wire name | Pixie | Meaning |
|---|---|---|
| `alert` | `ANGRY`, idle motion off, screen flash | something wants you now |
| `busy` | `DEFAULT` + curiosity on | agents are working |
| `done` | `HAPPY` + `anim_laugh()` | finished — go look |
| `calm` | `DEFAULT`, autoblink + idle motion | nothing happening |
| `offline` | `close()`, no motion | host not talking (see below) |

`offline` is a presentation override, not a semantic state — the host never
sends it. Transitions settle through `DEFAULT` first, as today, because moving
directly between two eyelid shapes leaves erase artifacts.

`done` must remain non-latching (already covered by an existing test).

### Host → state mapping

Priority order, unchanged from the current `PresenceMonitor`, with the last two
rows collapsed:

| Priority | Condition | State |
|---|---|---|
| 1 | activity/bell in a session that is not current | `alert` |
| 2 | an agent that was running in the current session stopped | `done` |
| 3 | anything running in the current session | `busy` |
| 4 | otherwise | `calm` |

`ACTIVE_LINGER` and the `ASLEEP` branch are deleted. Recent-input feedback is
already served by the glance layer and toasts.

---

## Glance: the pane list

Shown while the encoder is turning, and on session summon.

```
FOX webapp       2/4
─────────────────────
  1 claude
> 2 nvim
  3 npm test
```

- Header: slot label, session name, active pane position / total
- At most 5 rows, windowed host-side so the active pane is always among them
- `>` marks the active pane
- A trailing `*` or `!` marks activity or bell on the window that pane belongs
  to (tmux tracks these per window, not per pane)
- An empty session renders a single `(empty)` row

### Pane labels

A pane's label is, in order of preference:

1. A deliberate window name (not a generic shell name)
2. `claude` / `grok` / `opencode` when `presence.is_agent()` matches —
   **including the version-string form**, so a Claude Code pane reads `claude`
   rather than `2.1.261`
3. `pane_current_command`

Labels are truncated to 13 characters and sanitised host-side: `|` and
whitespace become `_`, because `|` is the wire delimiter.

### Summon shows the list

Pressing an animal key currently toasts `FOX - webapp`. That names the
destination but not its contents. It will show the pane list instead — strictly
more information, and one fewer concept to explain.

Toasts remain for events that are not list-shaped: `cla started`,
`OWL interrupted`, `OWL wants you`, `host offline`.

---

## Protocol

Replaces `STATE` and keeps `TOAST`.

```
FACE  <alert|busy|done|calm>
TOAST <text>                          1.8s, then face
LIST  <title>|<item>|<item>…          1.2s, then face
```

`LIST` is deliberately a **single atomic line**. A begin/item/end sequence can
be interrupted midway and leave the device rendering a half-built screen; one
line cannot. At 21 characters × 6 rows the payload fits well inside the
existing 200-character line buffer.

Example:

```
LIST FOX webapp 2/4|  1 claude|> 2 nvim|  3 npm test
```

The device splits on `|`: the first field is the title, the rest are rows,
rendered verbatim after truncation to 21 characters. Each `LIST` resets the
1.2s hold, so continuous encoder turning keeps the screen alive without the
host tracking duration.

**The host formats and windows the list**; the device only draws it. The host
sends at most 5 rows, already scrolled so the active pane is among them, with
markers and flags applied. This keeps every formatting rule in one testable
place and leaves the firmware a dumb renderer.

### Liveness

The host sends `FACE <state>` every 2s regardless of change. The firmware
already early-returns when the state is unchanged, so this restarts no
animation. The device treats *any* received command as a liveness tick.

No command for **5s** → `offline`: eyes close, idle motion stops, and a
`host offline` toast fires once on entry. This is unmistakably different from
`calm`, which is awake and blinking.

Recovery is automatic on the next command received.

---

## Burn-in

Mono OLEDs retain. Two cases:

- **`calm`** — idle motion stays on, so the eyes wander naturally. No extra
  work needed.
- **`offline` beyond 15 minutes** — the panel is blanked entirely. Nothing live
  is being shown, so there is nothing to lose. Any key press or host command
  restores it immediately.

---

## Boot

On power-up, before the first host command: `close()`, then `open()`, then two
`blink()`s, roughly one second total, then settle into `calm`.

Cheap, and it confirms the panel and I2C bus are alive before any host is
involved — which is exactly the moment you want that confirmation.

---

## Implementation notes

### Firmware (`v0/firmware/open_deck/open_deck.ino`)

- Replace the `PixieState` enum with the four states plus `offline`
- Add `LIST` parsing and a renderer that draws pre-formatted rows verbatim
- Add a `lastHostCommand` timestamp and the 5s/15s watchdogs
- Add the boot animation
- `FACE` replaces `STATE`

All rendering stays on the core-0 render task. Nothing here may run on the
input loop: a full framebuffer flush blocks ~29.5ms and would drop encoder
detents again.

### Host (`v0/bridge/opendeck/`)

- `presence.py` — collapse to four states, delete `ACTIVE_LINGER` and `ASLEEP`
- `face.py` — `FACE`/`LIST`/`TOAST`; add the 2s keepalive
- New `panes.py` — builds the whole list payload: labels, markers, flags,
  windowing, sanitisation, truncation
- `controller.py` — encoder turn and `summon` push a `LIST`; keepalive on the
  refresh tick

### Tests

Roughly 15 additions, all offline:

- Label mapping, including the version-string → `claude` case
- `|` and whitespace sanitisation
- Windowing keeps the active pane visible past 5 panes
- Empty session renders `(empty)`
- Four-state collapse, and `done` still not latching
- Keepalive is emitted on an unchanged state

---

## Risks

**The list is another thing to render, on a panel where a flush costs 29.5ms.**
It is static once drawn, so like the toast it is drawn and flushed once rather
than every frame. Cost is one flush per glance.

**`offline` could flap** if the host stalls briefly. The 5s threshold is 2.5×
the keepalive interval, which tolerates one missed tick.

**Claude Code's process name may change form.** The label rule matches both the
binary name and the version-string shape, so a change to either alone still
resolves.
