# Open Deck — Product Spec v0.2

A USB HID-style control surface for terminal AI coding agents
(Claude Code first; Grok CLI, OpenCode, Codex and others via profiles).

Hardware: XIAO ESP32S3 · 128×64 mono OLED (SH1106) · rotary encoder
(no push-switch) · 8 mechanical keys in a 2×4 matrix · USB-tethered.

---

## 1. The thesis

The hard part of running several coding agents at once is **not typing**.
It's **attention**:

- An agent hits a permission prompt and blocks. You don't notice for 6 minutes.
- Another finishes and sits idle awaiting review. You don't notice at all.
- A third is confidently doing the wrong thing and you'd stop it — if you were looking.
- You context-switch between panes just to answer "who needs me?"

A screen you already have can show this, but it competes with everything
else for the same visual space and the same window focus. A small,
dedicated, always-on display doesn't. **That's the entire justification
for this device existing.**

So the design goal is not "buttons that type things." It is:

> **Answer "which agent needs me, and what does it want?" without switching windows —
> and let me respond in one press.**

Everything below follows from that.

---

## 2. What the display is for

The OLED is 128×64 mono. At the default 6×8 font that's **21 characters ×
8 lines**. That's the real budget — every layout below is designed against it,
not against a wish.

### Mode A — Dashboard (default, idle-to-working state)

The home screen. One row per agent slot.

```
┌─────────────────────┐
│OPEN DECK      14:32 │
│                     │
│▸1 FOX  ●RUN   2m14s │
│ 2 OWL  ⏸NEED APPROVE│
│ 3 CAT  ✓DONE  ctx81%│
│ 4 PNDA ·idle        │
└─────────────────────┘
```

- `▸` marks the encoder's current selection (what ENTER will act on).
- Status glyphs: `●` running · `⏸` blocked/needs you · `✓` done, awaiting review ·
  `·` idle · `✕` errored/crashed.
- Elapsed time for running agents (how long has this been going?).
- `ctx%` when context is getting full — **the early warning that an agent is
  about to compact and start forgetting things.** This is one of the most
  genuinely useful numbers to surface and it's invisible in normal use until
  it bites you.

Any agent entering the blocked state makes the whole display **invert-flash
twice**, then settle with that row highlighted. That's the attention signal.

### Mode B — Approval (auto-raised, the killer feature)

When any agent blocks on a permission prompt, the deck raises this
automatically — you don't navigate to it:

```
┌─────────────────────┐
│⏸ APPROVE? · agent2  │
│                     │
│Bash                 │
│  rm -rf ./build     │
│  && npm run clean   │
│                     │
│ENT=yes  X=no  ⟳=more│
└─────────────────────┘
```

- ENTER approves, X denies. Both map to the harness's *own* native keys
  (see §4) — no clever translation needed.
- The encoder scrolls the command text when it's longer than fits.
- **Multiple pending approvals queue**; the header shows `⏸ 2 of 3` and the
  encoder moves between them.

### Mode C — Focus (single agent detail)

Hold an agent key, or ENTER on a dashboard row, to drill in: last tool call,
current file being edited, elapsed, context%, token spend. For "what is this
thing actually doing right now" without switching windows.

### Mode D — Palette (TERM key)

Encoder-scrollable list of saved prompts and slash commands
(`/compact`, `/clear`, `/tasks`, plus your own canned prompts —
"write tests for this", "review this diff", "explain this error").
ENTER sends it to the focused agent. This is the one place the device acts
like a traditional macro pad, and it's deliberately *not* the main mode.

### Mode E — Ambient / sleep

After N minutes with nothing running: dim, then show a minimal clock +
today's totals. **OLEDs burn in** — a static dashboard left lit for months
will ghost. Dim aggressively, shift pixels a little, and blank on true idle.

---

## 3. Key map

Eight keys, two layers (tap vs. hold ≈400ms). Hold is how we get 16 actions
out of 8 keys — necessary because **the encoder has no push-switch**, so it
can't be a confirm button.

Physical layout (verified on hardware):

```
 TERM   MIC    FOX    PANDA
 ENTER   X     CAT    OWL
```

| Key | Tap | Hold |
|---|---|---|
| **TERM** | Focus the selected agent's terminal window/pane | Start a new agent in a free slot |
| **ENTER** ✓ | Enter / approve the pending request | **Approve + "don't ask again"** (deliberately harder to reach — see §6) |
| **MIC** 🎙 | Toggle dictation (push-to-talk) | Hold-to-talk while held |
| **X** ✗ | Esc — deny the prompt, or interrupt the running agent | Esc Esc — rewind/edit previous message |
| **FOX / OWL / CAT / PANDA** | Select + focus that agent slot | **Interrupt that specific agent** without switching to it |

Two things worth calling out because they're the design working *with* the
harness instead of against it:

**ENTER and X are contextually correct in every mode, for free.** In Claude
Code, Enter submits *and* accepts a permission prompt; Esc denies a prompt
*and* interrupts a running agent. So one physical key = one semantic action
in every state, with no mode-tracking logic in the bridge. That's not a
coincidence to rely on blindly in other harnesses, but where it holds it
makes the mapping trivial.

**Hold-to-interrupt-a-specific-agent** is the sleeper feature. You see agent
3 going off the rails on the dashboard, you hold the CAT key, it stops.
You never left the window you were in.

---

## 4. Encoder — context-sensitive dial

One dial, meaning determined by the active mode. No push-switch, so it only
ever scrolls; ENTER commits.

| Mode | Encoder does |
|---|---|
| Dashboard | Move selection between agent slots |
| Approval | Scroll long command text / move between queued approvals |
| Palette | Scroll the command list |
| Focus | Scroll that agent's recent activity |
| Hold TERM + turn | Cycle permission mode (normal → auto-accept → plan) |

---

## 5. Where the status actually comes from

This is the part that makes or breaks the whole concept, so it gets a real
answer rather than hand-waving.

### Claude Code: hooks (the correct mechanism)

Claude Code has a hooks system that fires on lifecycle events, configured in
`settings.json`. The relevant ones:

| Hook | Tells us |
|---|---|
| `SessionStart` | Agent slot became active |
| `UserPromptSubmit` | Agent went from idle → working |
| `PreToolUse` | What it's about to do (feeds Focus mode) |
| `Notification` | **It needs permission or input — it's blocked** |
| `Stop` | Turn finished — done, awaiting review |
| `SubagentStop` | A subagent finished |

Each hook fires a tiny command; ours POSTs the event JSON to the bridge
daemon on `localhost`. The bridge keeps the agent state table and pushes
display updates to the deck. **This is real, first-class, and doesn't
require screen-scraping anything.**

### Other harnesses: fallbacks, in order of preference

1. **Native hook/event system** if it has one (mirror the Claude Code path).
2. **tmux pane scraping** — `tmux capture-pane -p` on a timer, regex for
   known prompt patterns. Harness-agnostic, works everywhere, but brittle
   against UI changes and this is where most of the per-harness maintenance
   burden will land. Be honest about that up front.
3. **Process state** (is it burning CPU?) — crude liveness only, no
   "blocked vs. thinking" distinction. Last resort.

The profile JSON declares which strategy a given harness uses, so adding a
harness stays a config change, not a code change.

---

## 6. Safety: approving things you can only half-see

A one-press physical approve button for AI agent actions is the best feature
here and also the most dangerous one. A 21-character-wide mono display can
show `rm -rf ./build` and `rm -rf ~/` almost identically if you're
half-looking. Design accordingly:

- **Never truncate silently.** If the command doesn't fit, show a `▾` and
  require the encoder to scroll before ENTER is armed. Reading is enforced by
  the interaction, not by good intentions.
- **"Approve and don't ask again" is hold-only**, never a tap. The
  irreversible-ish action costs deliberate effort.
- **Flag destructive patterns.** The bridge pattern-matches (`rm -rf`,
  `git push --force`, `DROP TABLE`, `curl … | sh`, credential paths) and
  renders those in inverted video with a `⚠` — and for those, ENTER requires
  a double-press.
- **Never auto-approve on a timer.** No "approves after 10s if you don't
  object." Ever.
- The deck is a *convenience* over the terminal prompt, never a replacement
  for it — the terminal prompt stays authoritative and always visible.

---

## 7. Protocol changes needed

The current spec (`protocol-spec.md`) is device→host only. The dashboard
requires host→device, so the wire protocol extends:

**Device → host** (existing, plus hold events):
```
EVT KEY_AGENT2 DOWN|UP|HOLD
EVT ENCODER +1
HB <uptime_ms>
```

**Host → device** (new). Semantic, not pixels — sending a 1KB framebuffer
over I2C-bound serial for every update would be wasteful and slow. The device
owns rendering:
```
SLOT <n> <name> <status> <elapsed_s> <ctx_pct>
APPROVE <agent> <tool> <text…>
MODE DASHBOARD|APPROVE|PALETTE|FOCUS|AMBIENT
ALERT <n>            ← invert-flash, attention signal
```

---

## 8. Known gap: the deck can't get your attention when you're not looking at it

Honest limitation of the v1 hardware. The display can flash, but a silent
flashing screen in your peripheral vision is a weak signal — the whole
premise is that you're *not* looking at it until it has something to say.

Cheap v2 additions that would fix this properly, in order of value:
1. **A piezo buzzer** — a single distinct chirp on "agent blocked" is worth
   more than every visual affordance in this document combined.
2. **An RGB LED** (or per-key LEDs) — ambient color-coded state visible from
   across the desk.
3. Haptics — probably overkill for a desk device that isn't held.

Worth designing the PCB with a buzzer footprint even if v1 doesn't populate it.

---

## 9. Build order

| Phase | Scope | Status |
|---|---|---|
| 0 | Hardware bring-up: display, encoder, 8-key matrix | ✅ validated |
| 1 | Bridge daemon + serial event parsing + keystroke injection | ✅ built |
| 2 | Claude Code hooks → bridge → Dashboard mode | ✅ built |
| 3 | Approval mode + destructive-command flagging | ✅ built, verified on hardware |
| 4 | Palette, Focus mode, hold-layer actions | ✅ built |
| 5 | Second harness profile (proves the abstraction) | ⏳ written, unverified |
| 6 | Custom PCB, buzzer, enclosure | 📋 not started |

**Phase 2 is the real milestone.** If the dashboard genuinely answers "who
needs me?" at a glance, the device is worth building. If it doesn't, no
amount of macro-key polish saves it.

### Verified end to end on hardware

```
physical key -> firmware safety gate -> serial -> bridge -> tmux send-keys -> agent pane
```

Confirmed: a destructive command cannot be approved before it has been
scrolled to the end and confirmed twice, and the resulting keystroke lands in
the correct tmux pane without stealing focus.

### Still unverified

The Grok and OpenCode profiles are written but have never run against those
harnesses — their tmux scrape patterns are a starting point, not tested. And
nothing here has yet run against a real Claude Code session over a long
working day, which is the only test that matters for the core premise.
