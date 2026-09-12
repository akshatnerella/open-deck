# Open Deck — Standalone Design

**Status:** REJECTED — built, then removed. See
[docs/decisions/no-hid.md](../../decisions/no-hid.md).

> Kept for the record. The reasoning below is wrong: it treats HID's
> inability to address a pane as a limitation to work around, when it is
> the reason the approach cannot work.
**Date:** 2026-09-10

Makes the deck a complete control surface with no daemon, and lets the daemon
upgrade it rather than enable it.

---

## The idea

Everything the daemon *does* is expressible as keystrokes, because **tmux
intercepts its prefix regardless of what is running in the pane**. `C-b :`
opens tmux's command prompt over the top of Claude Code, vim, anything.

```
C-b :  switch-client -t fox  ⏎
```

That works on any machine with tmux, **with no configuration at all**. An
earlier HID attempt sent `F13`-`F19` and required `.tmux.conf` bindings on
every machine, which is why its bare tier was worthless — three keystrokes you
already had. Typing real tmux commands needs nothing.

## Goals

1. Every key does its real job with no daemon and no config.
2. The display shows something true when alone, and everything when not.
3. The daemon upgrades the deck rather than enabling it.
4. No key can do two things at once.

## Non-goals

- Replacing the daemon. It stays strictly better (see Limits).
- Running an agent on the device.
- Wireless. Different project.

---

## Actions, standalone

| Key | Keystrokes sent | Config |
|---|---|---|
| FOX / OWL / CAT / PANDA | `C-b :` `switch-client -t <name>` `⏎` | none |
| TERM | `C-b %` then `<launch-command>` `⏎` | none |
| TERM (hold) | `C-b c` — new window | none |
| Encoder + / − | `C-b :` `select-pane -t :.+` / `:.-` `⏎` | none |
| X | `C-c` | none |
| MIC | `Space` | none |
| ENTER | `Enter` | none |

Session names are the slot labels lowercased — `fox`, `owl`, `cat`, `pnda`.
That already matches what the daemon names a session when it creates one for an
empty slot, so the two tiers agree without coordination.

### Two guards become unnecessary rather than missing

The daemon refuses to type a launch command into a pane running vim, because it
can see `pane_current_command`. A standalone deck cannot see that — so **TERM
always splits first**. A freshly split pane is always an idle shell, so the
check is not needed rather than skipped.

Likewise X sends only `C-c`, never `exit`. The daemon's "close an idle pane"
behaviour needs state; dropping it standalone means X can never destroy a pane
by mistake.

---

## The display, standalone

The rendering already lives on the device — the host only ever sends semantic
lines like `FACE busy`. The missing piece is data, and a keyboard cannot read.

### Dead reckoning: what the deck knows because it did it

| Knowable alone | Because |
|---|---|
| current session | the deck sent `switch-client` |
| selected slot | the deck tracks its own key presses |
| panes it created | the deck sent `split-window` |
| launch command in flight | the deck typed it |

That is enough for a truthful header (`FOX · fox`) and an idling Pixie.

**Dead reckoning drifts** the moment you use the real keyboard, and a status
display that drifts silently is worse than one that admits ignorance. So
standalone mode renders only what the deck did itself, and Pixie sits in a
neutral face rather than claiming to know what agents are doing.

### The loop that would close it, and why it is not the default

The deck is also a serial device the host can write to. It can type:

```
C-b : run-shell "tmux list-panes -a -F '…' > /dev/cu.usbmodem*" ⏎
```

and the host writes the answer straight back to the deck's own CDC endpoint.
`run-shell` executes regardless of what occupies the pane. Verified: a bare
`printf 'LIST …' > /dev/cu.usbmodem1101` drives the display with no daemon
running at all, so the return path is real.

**It is refresh-on-keypress only, never a timer.** Every poll injects
keystrokes into whatever currently has focus; a browser receiving
`C-b :run-shell…` every two seconds is unacceptable. Refreshing right after the
user pressed a deck key is safe, because they have just demonstrated they are
looking at the terminal.

Which means standalone state is *fresh when you act and stale afterwards* — the
opposite of a status display. Hence: opt-in, off by default.

---

## Arbitration

The device already knows whether a host is talking — the offline watchdog built
for the face. Reuse it, with the asymmetry proven necessary before:

| Situation | Threshold | Behaviour |
|---|---|---|
| No host has ever spoken | 5s | standalone: keystrokes + dead reckoning |
| Host spoke, then went quiet | 15s | standalone |
| Host talking | — | serial only; no keystrokes at all |

The long warm threshold exists because a daemon that stalls for six seconds
must not start typing `C-b :` into a browser. That failure mode is why the
earlier HID attempt needed it, and it applies unchanged here.

---

## Limits — the daemon stays strictly better

**Keystrokes go to the focused window.** The deck cannot target a pane; the
daemon's `tmux send-keys` can. Standalone acts on what you are looking at.

**No unsolicited events.** A keyboard cannot learn that an agent finished,
became blocked, or filled its context while it was not typing. Every one of
those is exactly the product's original premise — *which agent needs me* — and
none survive without a host.

**Encoder loses cross-window cycling.** `select-pane -t :.+` walks panes within
the current window; "next pane anywhere in the session" has no built-in tmux
command and is computed by the daemon.

So standalone is a complete *controller* and half a *display*. The half it
loses is the half the product was for — which is the honest reason the daemon
is not going away.

---

## Cost

HID requires `USBMode=default` (TinyUSB), which brings back:

- the serial port renaming between app and bootloader modes
- two-pass flashing, since the port moves under esptool mid-upload
- a firmware that fails to bring up USB makes its own port vanish (BOOT-button
  recovery)

That is a real tax, accepted this time because the standalone tier is the whole
control surface rather than three keystrokes.

**Every HID write must be gated on `tud_hid_n_ready()`.**
`USBHIDKeyboard::write()` sends two reports and `SendReport` defaults to a
100ms timeout, so writing to an unready endpoint stalls the input loop for up
to 200ms per keypress — the same class of bug that forced rendering onto the
second core, an order of magnitude worse.

---

## Build order

| Phase | Deliverable |
|---|---|
| 1 | `USBMode=default`, HID keyboard, `tud_hid_n_ready()` gate, arbitration — nothing typed yet |
| 2 | tmux command-prompt macros for every key |
| 3 | Dead-reckoned display for standalone mode |
| 4 | Verify: keys drive tmux with the daemon stopped; nothing types with it running |

Phase 4 is the only one that proves the point.
