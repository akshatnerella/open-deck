# Open Deck v0 — Bill of Materials

v0 is the **breadboard/hand-wired prototype**: no PCB, no battery, USB-tethered.
Everything here is off-the-shelf and hand-solderable. Total is roughly **$40–60**
depending on what's already in your parts bin.

---

## Electronics

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | **Seeed Studio XIAO ESP32S3** | 1 | The one used here is the plain S3 (not Sense). Dual-core 240MHz, 8MB flash, 8MB PSRAM. Seeed part **113991114** / LCSC **C20467913** |
| 2 | **1.3" OLED + EC11 rotary encoder combo module** | 1 | I2C, SH1106 driver, 128×64. PCB is **64.9 × 35 mm**. [Amazon B0DMYQHM9J](https://www.amazon.com/dp/B0DMYQHM9J) — see caveat below |
| 3 | **MX-compatible mechanical key switches** | 8 | Any MX-footprint switch. The keycap STLs in `cad/stl/` use an MX cross-stem |
| 4 | **1N4148 diode** | 1 | Only one is used (see "diodes" below) |
| 5 | **Solderless breadboard** | 1 | Half-size is enough |
| 6 | **Jumper wires (M/M and M/F)** | ~24 | 2 per key, 6 for the display module, plus power |
| 7 | **USB-C cable — data, not charge-only** | 1 | Charge-only cables cost hours of debugging here. Verify it enumerates |

### Caveat on the display module

This is a generic unbranded combo board with **no authoritative datasheet**.
Listings from different sellers disagree on dimensions. Confirmed by direct
measurement on the actual unit:

- PCB: 64.9 × 35 mm
- Display: 1.3", 128×64, **SH1106** controller (not SSD1306 — this matters,
  SSD1306 drivers render garbage on it), I2C address `0x3C`
- Encoder: EC11, 20 pulses/rotation, knurled shaft ~15 mm long
- Knob: 15 mm diameter aluminium — **this is the knob, not the shaft**. The
  panel cutout must fit the ~6 mm shaft, not the knob
- **The push-switch on our unit was dead.** Verified with a raw pin-state
  probe: the SW line never moved. Buy assuming you may not get a working
  encoder click — the firmware doesn't use it

If yours has a working push-switch, you have a free extra input and `D7`
could return to it (see the pin map).

### On diodes

A full 8-key matrix normally wants one diode per key to prevent ghosting.
**v0 uses only one** (a leftover from bring-up) and that's fine here:

Ghosting needs three keys held simultaneously in an L-shape across both rows.
A macro pad is pressed one key at a time — there are no chords. The firmware
instead drives rows `OUTPUT_OPEN_DRAIN`, so two keys sharing a column across
rows can't short one row's output into the other, which is the failure that
actually matters electrically.

Add 7 more 1N4148s if you want textbook-correct n-key rollover. v1's PCB will
include them.

---

## 3D-printed parts

Print in PLA. Files in `cad/stl/`.

| Part | Qty | Notes |
|---|---|---|
| `Top Shell.stl` | 1 | Display window, encoder hole, 8-key grid |
| `Bottom Shell.stl` | 1 | Base |
| `Key Cap Terminal / Yes / Mic / No.stl` | 1 each | Utility keys — print **white** |
| `Key Cap Fox / Owl / Cat / Panda.stl` | 1 each | Agent keys — print in 4 **distinct colours** (red / blue / yellow / green) so you can tell agents apart at a glance without looking down |

**Multi-colour printing:** if you're swapping filament manually, print each
colour as a *separate job* rather than one multi-colour plate. A single plate
with colour changes forces the slicer to generate a purge/prime tower, which
wastes filament on 8 small parts. Separate jobs = no tower at all.

The `cad/dxf/` badge outlines are the icon geometry, if you want to remix the
keycaps. The four animal icons are traced from
[OpenMoji](https://openmoji.org/) (CC BY-SA 4.0); thin whiskers and talons were
morphologically removed because they don't survive FDM at keycap scale.

---

## Wiring

Full pin map in [`../docs/protocol-spec.md`](../docs/protocol-spec.md).

**Display + encoder module → XIAO**

| Module | XIAO |
|---|---|
| VCC | 3V3 (**not 5V**) |
| GND | GND |
| SDA | D4 |
| SCL | D5 |
| CLK | D3 |
| DT | D6 |
| SW | *unused* |

**8-key matrix** — rows `D0`, `D1`; columns `D7 D8 D9 D10` **left to right**.

| | C1 (D7) | C2 (D8) | C3 (D9) | C4 (D10) |
|---|---|---|---|---|
| **R1 (D0)** | TERM | MIC | FOX | PANDA |
| **R2 (D1)** | ENTER | X | CAT | OWL |

Each key: **row pin → switch leg A, switch leg B → column pin.** That's it.

⚠️ The column order was determined **empirically** — by pressing R1C1…R2C4 in
sequence and reading back what the device reported — and it is the reverse of
what the wiring notes suggested. If you rebuild this and keys come out
mirrored, that's why. Don't re-derive it from a diagram; measure it.

`D2` (GPIO3) is deliberately left unused: it's an ESP32-S3 **strapping pin**,
and a switch on it could interfere with boot-mode sensing if pressed at
power-on.

---

## Deliberately not in v0

| Item | Why |
|---|---|
| **LiPo battery (1200 mAh)** | Wired and tested, then cut. The bridge is USB-tethered anyway, so the battery only added a charging failure mode with no benefit. The XIAO's onboard charger handles it if you want it — mind the polarity |
| **External antenna** | The XIAO S3 ships with a u.FL FPC antenna and needs it for WiFi/BLE. v0 talks over USB serial, so it's unnecessary. If you add it later: stick it to an **inside plastic wall**, away from metal and the battery, and don't crease it |
| **Piezo buzzer** | Not bought, but **it's the single highest-value addition**. A silent flashing display can't get your attention when you aren't looking at it — which is the entire premise of the device. One chirp on "agent blocked" would be worth more than every visual affordance in this repo. v1 should populate one |
