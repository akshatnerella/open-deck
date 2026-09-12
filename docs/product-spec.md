# Open Deck — Design Notes

Why the device is shaped the way it is. For protocol details see
[protocol-spec.md](protocol-spec.md); for building one see
[../v0/README.md](../v0/README.md).

---

## The idea

Running several coding agents at once, the bottleneck isn't typing — it's
**context switching**. Which project was that in? Which pane is the agent in?
Where did I leave the tests running?

The deck maps that onto hardware you can hit without looking:

- **Four animal keys → four tmux sessions.** Coarse: which project.
- **Encoder → panes within that session.** Fine: which terminal.

The key insight, and the one that came from the user rather than the design:
**tmux sessions are a real thing you already have.** An earlier version
invented "agent sessions" as an abstraction and asked you to adopt it. Mapping
to tmux instead means the deck fits an existing workflow rather than replacing
one, and it makes the hardware's job legible — a preset button and a tuning
dial, like a radio.

---

## Why tmux does most of the work

tmux already tracks, per window, whether there's been **activity** or a
**bell** since you last looked. That's precisely the "something happened where
you aren't watching" signal the device needs — available from one subprocess
call, with no agent integration, no hooks, and no screen scraping.

An earlier design got this from Claude Code's hook system. That worked, but it
was Claude-Code-specific, needed `settings.json` edits, and broke entirely
under `--dangerously-skip-permissions`. tmux gives the same signal for every
harness for free.

---

## Pixie

The face is [Pixie](https://github.com/akshatnerella/pixie), drawn
procedurally by RoboEyes — the same character, ported from her 320×240 colour
panel to the deck's 128×64 mono OLED. Her expression is derived from tmux
state, evaluated in strict priority order so two simultaneously-true signals
can't make the face flap:

| Priority | State | Trigger |
|---|---|---|
| 1 | `attention` | activity/bell in a session you are **not** in |
| 2 | `done` | an agent that was running here stopped |
| 3 | `working` | something is running in the current session |
| 4 | `active` | you touched the deck (4s linger) |
| 5 | `idle` | shells only |
| 6 | `asleep` | 5 min untouched, or no sessions |

`done` is explicitly non-latching, or she'd stay grinning forever.

Notifications are **toasts**: one line, 1.8s, replacing the face. Subtle by
construction — they interrupt briefly rather than becoming permanent chrome.

---

## Things learned the hard way

Each of these cost real debugging time and is now pinned by a test or a
comment in the code.

**The display was eating the encoder.** A full SH1106 flush blocks 29.5ms;
RoboEyes wants a frame every 20ms. On one thread the encoder was never sampled
during a flush, so detents weren't delayed — they were dropped. Fixed by
pinning rendering to the second core. This looked like host-side lag and
wasn't; measuring the host first (12ms/poll, 7ms/detent) ruled it out before
any code changed.

**Claude Code reports its version as the process name.** `pane_current_command`
returns `2.1.261`, not `claude`. An allowlist of binary names silently misses
every running agent. Matched by shape as well as name.

**Column order was mirrored.** Physical left-to-right is `D7 D8 D9 D10`, the
reverse of the wiring diagram. Determined by pressing keys in sequence and
reading back the reported names. Guessed twice, wrong twice; measuring took one
round.

**Ghostty needs `-e` with separate argv entries.** `--args -e "tmux attach -t x"`
opens a window that runs nothing. And it uses non-native fullscreen, so
`AXFullScreen` reads `false` even when fullscreen — a "toggle unless already
fullscreen" check exits fullscreen every time. Fullscreen is set at launch
only.

**Never type into a busy pane.** `launch_agent` refuses when the pane is
running a program; injecting a command into someone's editor is unrecoverable.
The double-tap split path skips the check because a fresh pane is always an
idle shell.

---

## Not built

**Approvals.** A physical approve/deny button for agent permission prompts was
designed and built, then removed: it depends on the harness *asking*, and the
day-to-day launch command here is `grok`, which does not gate tool use.
The two are mutually exclusive by construction. The design notes are in git
history if that changes.

**A buzzer.** The deck still can't get your attention when you aren't looking
at it; a flashing face in peripheral vision is a weak signal. One chirp on
"agent blocked" would be worth more than every visual affordance here. v1's PCB
should populate one.
