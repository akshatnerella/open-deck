# Open Deck — HID Design

**Status:** REJECTED — built, then removed. See
[docs/decisions/no-hid.md](../../decisions/no-hid.md).

> Kept for the record. The reasoning below is wrong: it treats HID's
> inability to address a pane as a limitation to work around, when it is
> the reason the approach cannot work.
**Date:** 2026-09-10

Makes the deck work as a plain USB keyboard on a machine with nothing
installed, while keeping the full tmux experience where the daemon is running.

---

## Why

Today the deck is inert without its daemon. Plugging it into another Mac means
cloning the repo, building a venv, installing `pyserial`, having tmux, and
running a launchd agent. A macro pad that needs a Python daemon on every
machine is not really a peripheral — it is software with a keyboard attached.

The ESP32-S3 can enumerate as **HID keyboard and CDC serial at the same time**,
which gives the device two tiers:

| Tier | Needs | Gets |
|---|---|---|
| **Bare** | nothing | keys send real keystrokes |
| **Bare + 6 lines of `.tmux.conf`** | tmux | session switching too |
| **Full** | the daemon | targeted delivery, Pixie, the pane list |

The deck degrades instead of dying.

## Goals

1. Keys do something useful on a machine with nothing installed.
2. The full experience is unchanged where the daemon runs.
3. No double-firing: a keypress never produces two actions.
4. Nothing already built is thrown away — same protocol, same daemon.

## Non-goals

- Replacing the daemon. HID is strictly less capable (see below).
- Mouse, consumer-control or gamepad HID.
- Configuring the HID keymap at runtime.

---

## The central constraint

The board currently builds as **`USBMode=hwcdc`** — the hardware USB-Serial/JTAG
peripheral. macOS enumerates it as `USB JTAG_serial debug unit`. That peripheral
**cannot do HID at all**.

HID requires **`USBMode=default`** (USB-OTG / TinyUSB), which supports a
composite HID+CDC device. Verified: both a HID sketch *and* the existing
firmware compile unchanged under that FQBN.

```
esp32:esp32:XIAO_ESP32S3:USBMode=default
```

Cost: ~43KB flash (9% → 11%) and ~2KB RAM. No code rewrite.

**This FQBN must be pinned everywhere** — README, `v0/README.md`, and any build
script. A build with the default FQBN silently produces a device with no HID
and no obvious symptom beyond "the keys stopped working on my other laptop".

---

## HID keymap

Only fires when the daemon is absent (see arbitration).

| Key | HID output | Rationale |
|---|---|---|
| ENTER | `Return` | Claude Code submits and accepts prompts with it |
| X | `Escape` | Claude Code interrupts and denies with it |
| MIC | `Space` | the voice-mode toggle |
| FOX / OWL / CAT / PANDA | `F13` / `F14` / `F15` / `F16` | bindable, collide with nothing |
| TERM | `F17` | ditto |
| Encoder − / + | `F18` / `F19` | ditto |

`F13`–`F24` are real HID keycodes that essentially no application binds by
default — verified present in the core's `USBHIDKeyboard.h` as `0xF0`–`0xFB`.
That makes them safe to send blind on an unknown machine: on a bare box they do
nothing, and where the user wants more they are free to bind.

### The zero-install tmux tier

Six lines gets session switching with no daemon at all:

```tmux
bind-key -n F13 switch-client -t fox
bind-key -n F14 switch-client -t owl
bind-key -n F15 switch-client -t cat
bind-key -n F16 switch-client -t pnda
bind-key -n F18 previous-window
bind-key -n F19 next-window
```

Ship this as `v0/bridge/scripts/opendeck.tmux.conf` with a one-line install note.

Note the encoder degrades here: HID mode cycles *windows*, not panes, because
tmux has no built-in "next pane across the session" binding. That is a real
capability loss and belongs in the docs, not hidden.

---

## Arbitration: never two actions from one press

The danger is obvious — if HID and the daemon both act, pressing X sends
`Escape` **and** the daemon sends `C-c`.

The device already knows whether a host is alive: the offline watchdog built
for the face. Reuse that signal rather than inventing a second one.

**Host alive → serial only. Host absent → HID only.**

But a single threshold is wrong here, because the two failure modes differ:

| Situation | Threshold | Why |
|---|---|---|
| No host has *ever* spoken since boot | **5s** (the existing boot grace) | this is a bare machine; make the keys work quickly |
| A host spoke, then went quiet | **15s** | probably a hiccup — a slow tmux call, a daemon restart |

The asymmetry matters. With one short threshold, a daemon that stalls for six
seconds would silently start typing `Escape` into whatever window happens to be
focused — possibly a browser. Requiring a longer, deliberate absence before
arming HID makes that misfire implausible while still recovering automatically.

This is the one place where the watchdog stops being cosmetic and starts
gating behaviour, so it needs saying plainly: **a long daemon outage changes
what the keys do.** The display already announces it (eyes closed, `host
offline`), which is the honest signal that the deck is in its degraded tier.

### State

```c
bool hostEverSeen;              // set on the first host command after boot
unsigned long lastHostCommand;  // already exists
```

```
hidArmed = !hostAlive && (hostEverSeen ? absent > 15s : absent > 5s)
```

`hidArmed` is computed on the input core, since that is where key events are
handled. It is a read of a `volatile` word written by the same core — no new
cross-core state, no new mutex.

---

## What HID cannot do

Worth stating so nobody expects otherwise:

**HID types into the focused window.** It cannot target a pane. The daemon's
`tmux send-keys` reaches the right pane regardless of focus; HID cannot. So the
bare tier can interrupt *what you are looking at*, not "agent 3 over there".

**No pane list, no Pixie state.** Those need a host to compute them. On a bare
machine Pixie sits in her offline face, which is accurate — there is no host.

**The encoder loses pane granularity** in the tmux tier, as above.

HID is a graceful degradation, not a second implementation of the product.

---

## Risk: flashing gets sharper teeth

Under `hwcdc`, the serial port is produced by dedicated silicon and exists
whatever the firmware does. Under TinyUSB, **the firmware creates the port**. A
build that fails to bring up USB makes the port vanish, and recovery is the
BOOT-button sequence rather than a plain re-flash.

This project has already lost hours to a board that would not enumerate, so the
recovery path goes in the docs *before* it is needed:

1. Unplug.
2. Hold **BOOT**.
3. Plug in, keep holding ~2s, release.
4. Flash normally — the bootloader's port is independent of app firmware.

Keep `CDCOnBoot=Enabled` (already the default) so the port comes up before
`setup()` runs, which means even a hanging sketch stays flashable.

---

## Build order

| Phase | Deliverable |
|---|---|
| 1 | Switch FQBN to `USBMode=default`, flash, confirm the serial port and the daemon still work end to end. **Nothing else changes.** |
| 2 | Add `USBHIDKeyboard`, the keymap, and `hidArmed` arbitration |
| 3 | `opendeck.tmux.conf` + docs, including the degradation table and BOOT recovery |
| 4 | Verify on a second Mac with nothing installed |

**Phase 1 is the gate.** It is a one-line change that proves the USB mode switch
survives on real hardware before any HID code is written. If the port does not
come back cleanly, that is worth knowing while the diff is one line — not
buried under a keymap.

Phase 4 is the only phase that proves the point of the whole exercise.

---

## Open question for later

Should the daemon *suppress* HID explicitly rather than relying on silence — a
`HID off` command on connect, `HID on` at shutdown? It would make the handoff
deterministic instead of timing-based.

Deliberately deferred: it adds protocol surface and a failure mode of its own
(a daemon killed with `SIGKILL` never sends the re-enable, leaving HID dead
until reboot). The timing rule recovers on its own from every failure,
including the ones nobody planned for. Revisit only if the 15s rule misfires in
real use.
