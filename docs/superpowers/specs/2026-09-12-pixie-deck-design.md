# Pixie Deck — product design

**Status:** proposed
**Date:** 2026-09-12
**Supersedes:** the "control surface for tmux" framing in `docs/product-spec.md`

Turns the deck from a tmux accessory into a desk product: four projects, four
keys, a character who tells you how they are doing. tmux stays — as plumbing
the owner never sees.

---

## Why it currently feels like a tool

Three concrete things, all fixable:

**1. It assumes tmux fluency.** `SlotTable` binds keys to sessions that already
exist. You create sessions, you name them, and the deck finds them. A key
pointing at nothing does nothing — so the device is inert until you have
already done the work by hand.

**2. Setup is a text file.** Pinning a slot means editing
`~/.config/opendeck/config.json` and restarting. Nothing about the physical
object participates in its own configuration, even though it has a screen, a
scroll wheel, and eight buttons.

**3. Every feature is a tmux command wearing a costume.** `summon` is
`switch-client`. The encoder is `select-pane`. The animals are decoration on
top of a keybinding you already had. There is no reason to want the object.

The fix is one decision: **the deck owns the projects, not the sessions.**

---

## The reframe

> Four keycaps. Four projects. Press one and you are working on it.

A slot is a **project** — a directory with a name and an animal. The deck
creates its session, opens the terminal, launches the agent, and remembers.
The owner never types `tmux`, never names a session, never edits a config.

| | Tool (today) | Product |
|---|---|---|
| A key means | a tmux session that exists | a project you work on |
| Empty key | does nothing | offers to set itself up |
| Binding | edit JSON, restart | encoder + press, on the device |
| Requires | knowing tmux | knowing which project you want |
| tmux is | the interface | an implementation detail |

Everything below follows from that.

---

## First run

The moment that decides whether this is a product. Plug in a deck that has
never been used:

```
1.  Pixie wakes, stretches, blinks.          "hello"
2.  The slot strip shows four empty pens.    · · · ·
3.  Press any animal key.
4.  The picker opens: recent git repos,
    most-recently-touched first.             turn to choose
5.  Press to confirm.
6.  The deck creates the session, opens the
    terminal, launches the agent.            FOX -> open-deck
```

Under a minute from plugging in to an agent running, with no typing. That is
the demo.

**Project discovery** scans for git repositories under the usual roots
(`~/Developer`, `~/Documents`, `~/src`, `~/code`, `$HOME`), ranked by most
recent commit — the same ordering an editor's "recent projects" uses, and it
is right nearly every time. No index, no daemon config: the scan runs when the
picker opens and caches for the session.

**Binding is remembered** in `~/.config/opendeck/decks.json`, written by the
deck, not by the owner. It is a cache with an obvious shape, not a config file
with a schema to learn. Deleting it costs one re-pick.

---

## The display, as a designed system

Five screens. Every pixel has an owner, and transitions between them are
defined rather than incidental.

### Home — Pixie, plus the fleet at a glance

```
+---------------------+
|                     |
|      ^   ^          |
|     ( o   o )       |    Pixie: 48px
|        ---          |
|                     |
+---------------------+
| FOX. OWL@ CAT! PNDA |    slot strip: 16px
+---------------------+
```

The slot strip is the product's whole value in one row: four projects, four
states, readable from across a desk without focusing your eyes.

| Glyph | State |
|---|---|
| (blank) | slot is empty |
| `.` | idle — a shell, nothing running |
| `@` | working — an agent is busy (animates) |
| `!` | needs you — blocked, or asking |
| `*` | done — finished since you last looked |

Pixie's expression is the same information at lower resolution: one glance
tells you *whether* anything needs you, the strip tells you *which*.

### Peek — hold any key

Holding a key shows what it will do, laid out in the same 2×2 arrangement as
the physical keys under your other hand. A chord system nobody can discover is
a party trick; this makes the device teach itself, and removes the manual.

```
Hold FOX:            +---------------------+
                     | FOX  open-deck      |
                     | working  ctx 62%    |
                     |---------------------|
                     | new    | interrupt  |
                     | speak  | approve    |
                     +---------------------+
```

Release without a second key and nothing happens — peeking is free, which is
what makes it safe to explore.

### Picker — encoder

A list bound to the encoder: projects when a slot is empty, panes when it is
not. Press to commit, any other key to cancel.

### Alert — something needs you

Pixie scowls, the strip marks the slot, a line names it. Latches until
acknowledged, because the whole point is that you were not looking.

### Sleep

After five idle minutes the panel blanks except for Pixie breathing. The deck
is furniture that occasionally has something to say, not a dashboard demanding
attention.

---

## Input grammar

The physical layout is already right and nobody planned it:

```
TERM   MIC     FOX   PNDA        left hand: verbs
ENTER  CANCEL  CAT   OWL         right hand: targets
```

Verbs under one hand, targets under the other. That is a two-handed chord
keyboard, so the grammar is **verb + target**:

| Input | Meaning |
|---|---|
| Tap target | go to that project (set it up if empty) |
| Hold target | peek: status + what the verbs will do |
| Hold target, turn encoder | scrub that project's panes without leaving yours |
| Hold target, tap verb | **apply the verb there without going there** |
| Tap verb | apply to where you are |
| Turn encoder | move between panes here |
| Hold TERM, turn encoder | command palette |

The fourth row is the one tmux cannot do and the reason to own the object:
**interrupt the agent in CAT while you keep reading OWL.** Every keybinding
alternative requires switching first.

Double-tap stays reserved for one shortcut per key, assigned from real use
rather than invented now. Today's `KEY_TERM` double-tap-to-split is the
template.

### One thing to fix

Slot numbering does not match reading order: `FOX PNDA / CAT OWL` on the keys,
but slots 0–3 are `FOX OWL CAT PNDA`. Harmless internally, wrong the moment a
screen lists them in slot order. Renumber to match what the eye sees.

---

## Pixie as the product, not the paint

She already earns her place: her expression is derived from real state, in
strict priority order, so two true signals cannot make the face flap. Three
additions make her the reason to keep the thing on a desk.

**She reacts to you, not just to the agents.** Coming back after ten minutes
away should look different from never having left. The deck knows — it sees
key events.

**She has an opinion about time.** An agent working for two minutes is normal;
one stuck for twenty is worth a worried look, and nothing in the current state
machine can express that.

**She is never wrong.** The existing offline rule — eyes closed when the host
stops talking — is the single most important thing about her, and it stays.
A face that keeps smiling when it has no idea what is happening is worse than
a blank screen, because it is confidently wrong.

What she does **not** get: voice, wake word, or a brain. Those are Pixie the
companion's job, in Pixie's repo. Here she is a character and a status
display, which is exactly enough.

---

## What gets deleted

Productising is mostly subtraction:

- **Hand-editable `config.json`** as the binding mechanism. The deck writes
  its own bindings. Keep a config for genuine preferences (launch command,
  terminal) and stop pretending session pinning is a preference.
- **`profiles/`** as a user-facing directory. Harness differences become
  detection plus one question at first run.
- **"Run your agents under tmux and the deck picks them up"** from the README.
  That sentence is the tool framing in one line.
- **Slot assignment by discovery.** Sticky-on-first-sight is clever and
  unpredictable. Bindings are explicit, owned, and visible.

---

## Build order

| Phase | Deliverable | Proves |
|---|---|---|
| 1 | Slot strip on the home screen | the glanceable-fleet claim |
| 2 | Peek on hold | the device teaches itself |
| 3 | Project picker + `decks.json` | no config file, no tmux |
| 4 | Create-on-empty: session, terminal, agent | a key always does something |
| 5 | Verb+target chords | the thing keybindings cannot do |
| 6 | First-run flow end to end | the demo |

Phases 3 and 4 are the product. 1 and 2 are worth shipping first because they
are visible, self-contained, and make the next three easier to judge.

---

## Open questions

**More than four projects.** Four keycaps, more repos. Options: hold-encoder
to page between banks of four; or accept four as the product's opinion. Worth
resisting the urge to solve now — four may simply be the right number, and
"an opinion" is a product property.

**The bridge is still a launchd script.** One command, but a shell script.
A signed menu-bar app is the honest end state and a real amount of work;
worth doing only once the rest is settled.
