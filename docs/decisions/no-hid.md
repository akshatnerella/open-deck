# The deck is not a keyboard

**Decided:** 2026-09-12 · **Status:** settled

Open Deck does not enumerate as a USB HID device and never sends keystrokes.
It speaks a line protocol over USB CDC serial; a host bridge decides what its
events mean.

This has now been proposed, built, and removed **twice**. This note exists so
it is not proposed a third time.

## Why it keeps getting proposed

The bridge used to need an install: a venv and `pyserial`, on Python 3.11 when
macOS ships 3.9. Plugging the deck into a second Mac meant a setup ritual, and
"just make it a keyboard" removes that ritual completely. The reasoning is
sound right up to the point where you ask what a keystroke can address.

## Why it is wrong

**A keyboard has no addressing.** `tmux send-keys -t fox:1.2` names the pane it
talks to. HID names nothing — it types into whatever holds focus, which is a
property of the window server, not of the device. The deck cannot read focus,
so it cannot know whether its keystrokes are landing on tmux, a browser, or a
text field.

The product's whole premise is *which agent needs me, act on that agent*. That
is an addressing problem. A transport that cannot address cannot implement it.

**Every mitigation is a patch on that same flaw**, and they were all tried:

| Mitigation | Why it failed |
|---|---|
| `F13`–`F19`, harmless unbound keycodes | Needed `.tmux.conf` on every machine, which is the install step HID was meant to remove. The bare tier was then three keystrokes you already had. |
| tmux command prompt (`C-b :`), needs no config | Types ~25 characters. Sent `:select-pane -t :.+` into a live Claude Code session. |
| Built-in prefixed keys (`C-b o`), 2 keystrokes | Smaller blast radius, same flaw. An encoder emits dozens of events: `o;;ooo;;;ooo`. |
| Default off, armed by a deliberate chord | A device whose headline feature must be switched on, and which is unsafe once it is. |

Making each misfire smaller was the wrong axis entirely. The fix is a device
that cannot type.

## What replaced it

The reason HID looked necessary — the host install — was removed directly:

- **`pyserial` deleted.** `opendeck/serialport.py` does 8N1 raw termios in
  ~100 lines. The bridge now has zero third-party dependencies.
- **Python floor lowered to 3.9**, the version macOS ships, via two shims in
  `opendeck/compat.py`.

So the install is now `./open-deck`, on any Mac, with nothing installed —
which is what HID was for.

## The honest trade

The deck does nothing until the bridge runs. That is a real cost and it is not
hidden: no bridge, no function.

It buys pane-level addressing, a display that reports agent state the device
cannot observe alone, and a device that is physically incapable of typing into
the wrong window. Stream Deck, Loupedeck, and every MIDI control surface make
the same trade. A control surface is not a keyboard.

## If you are about to propose it again

Answer this first: **how does a keystroke reach a specific tmux pane when the
user is looking at a browser?** Every previous attempt failed on that question,
and it has no answer within HID. If the goal is reducing install friction, the
bridge already installs in one command with no dependencies — reduce it further
there, not by changing what the device is.
