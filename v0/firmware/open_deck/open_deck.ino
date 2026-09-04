// Open Deck - AI agent control surface firmware
//
// Hardware: XIAO ESP32S3 | SH1106 128x64 mono OLED (I2C) | EC11 encoder
// (rotation only, push-switch dead/unused) | 8 keys in a 2x4 matrix.
//
// The device is a dumb-but-pretty renderer: it emits semantic input events
// over USB serial and renders whatever state the host bridge pushes back.
// It knows nothing about Claude Code / Grok / OpenCode - see docs/product-spec.md.
//
// ---- Wire protocol ----
// Device -> host:
//   EVT <KEY_NAME> DOWN|HOLD|UP
//   EVT ENCODER <+n|-n>
//   HB <uptime_ms>
// Host -> device:
//   SLOT <0-3> <name> <idle|run|blocked|done|error> <elapsed_s> <ctx_pct>
//   APPROVE <agent> <0|1 danger> <tool> <text...>
//   APPROVE_CLEAR
//   PALETTE_CLEAR
//   PALETTE_ADD <text...>
//   MODE <DASHBOARD|APPROVE|PALETTE|FOCUS|AMBIENT>
//   ALERT
//   FOCUS_LINE <0-3> <text...>

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// ---------- pins ----------
#define OLED_ADDR    0x3C
#define SDA_PIN      D4
#define SCL_PIN      D5
#define ENC_CLK_PIN  D3
#define ENC_DATA_PIN D6

// 2 rows x 4 cols. Physical layout (index = row*4 + col):
//   R1C1 TERM   R1C2 MIC     R1C3 FOX(1)  R1C4 PANDA(4)
//   R2C1 ENTER  R2C2 CANCEL  R2C3 CAT(3)  R2C4 OWL(2)
// This array is the single source of truth for the mapping - everything else
// keys off the names, so a rewire only changes this one list.
// Column pin order verified empirically by pressing R1C1..R2C4 in sequence and
// reading back what the device reported: physical left-to-right is D7 D8 D9 D10.
const uint8_t ROW_PINS[2] = { D0, D1 };
const uint8_t COL_PINS[4] = { D7, D8, D9, D10 };

const char* KEY_NAMES[8] = {
  "KEY_TERM",  "KEY_MIC",    "KEY_AGENT1", "KEY_AGENT4",
  "KEY_ENTER", "KEY_CANCEL", "KEY_AGENT3", "KEY_AGENT2"
};


Adafruit_SH1106G display(128, 64, &Wire, -1);

// ---------- input state ----------
bool keyState[8]    = {false};
bool keyRaw[8]      = {false};
bool keyHoldSent[8] = {false};
unsigned long keyChangeTime[8] = {0};
unsigned long keyDownTime[8]   = {0};
const unsigned long DEBOUNCE_MS = 25;
const unsigned long HOLD_MS     = 400;

static const int8_t rot_enc_table[] = {0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0};
static uint8_t prevNextCode = 0;
static uint16_t encStore = 0;

// ---------- display state (pushed from host) ----------
enum Mode { MODE_DASHBOARD, MODE_APPROVE, MODE_PALETTE, MODE_FOCUS, MODE_AMBIENT };
Mode mode = MODE_DASHBOARD;

enum Status { ST_IDLE, ST_RUN, ST_BLOCKED, ST_DONE, ST_ERROR };

struct Slot {
  char     name[9];
  Status   status;
  uint32_t elapsed;   // seconds
  uint8_t  ctxPct;
};
Slot slots[4];

int  selection = 0;          // dashboard cursor / palette cursor

char approveAgent[9]  = "";
char approveTool[17]  = "";
char approveText[321] = "";
bool approveDanger    = false;
int  approveCount     = 1;       // how many requests are queued (cosmetic only)
int  approveScroll    = 0;
bool approveArmed     = false;   // must read to the end before ENTER counts
bool approveConfirm   = false;   // second press required for dangerous ops

#define PALETTE_MAX 12
char paletteItems[PALETTE_MAX][22];
int  paletteCount = 0;

char focusLines[4][22];

unsigned long alertUntil = 0;
bool displayDirty = true;

// Key identity helpers - everything keys off KEY_NAMES so a rewire only
// touches that one array. (Defined after the enums above: the Arduino
// preprocessor injects generated prototypes before the first function
// definition in the file, so helpers placed higher would push those
// prototypes above the type declarations they depend on.)
bool isKey(uint8_t idx, const char* name) { return strcmp(KEY_NAMES[idx], name) == 0; }

// Agent key -> slot index, or -1 if this key isn't an agent key.
int agentSlot(uint8_t idx) {
  if (isKey(idx, "KEY_AGENT1")) return 0;
  if (isKey(idx, "KEY_AGENT2")) return 1;
  if (isKey(idx, "KEY_AGENT3")) return 2;
  if (isKey(idx, "KEY_AGENT4")) return 3;
  return -1;
}

// ---------- non-blocking serial ----------
// ESP32-S3 native USB CDC blocks on write once its TX ring fills with no host
// reading. These prints live inline in loop(), so a blocked write would stall
// the matrix scan and the display too. Drop the line instead of blocking.
void emit(const String &line) {
  if (Serial.availableForWrite() >= (int)line.length() + 2) Serial.println(line);
}

int8_t read_rotary() {
  prevNextCode <<= 2;
  if (digitalRead(ENC_DATA_PIN)) prevNextCode |= 0x02;
  if (digitalRead(ENC_CLK_PIN))  prevNextCode |= 0x01;
  prevNextCode &= 0x0f;
  if (rot_enc_table[prevNextCode]) {
    encStore <<= 4;
    encStore |= prevNextCode;
    if ((encStore & 0xff) == 0x2b) return -1;
    if ((encStore & 0xff) == 0x17) return 1;
  }
  return 0;
}

// ---------- rendering helpers ----------
void fmtElapsed(uint32_t s, char* out, size_t n) {
  if (s == 0)        snprintf(out, n, " ");
  else if (s < 60)   snprintf(out, n, "%lus", (unsigned long)s);
  else if (s < 3600) snprintf(out, n, "%lum%02lus", (unsigned long)s/60, (unsigned long)s%60);
  else               snprintf(out, n, "%luh%02lum", (unsigned long)s/3600, (unsigned long)(s%3600)/60);
}

const char* statusLabel(Status s) {
  switch (s) {
    case ST_RUN:     return "RUN";
    case ST_BLOCKED: return "BLOCK";
    case ST_DONE:    return "DONE";
    case ST_ERROR:   return "ERR";
    default:         return "idle";
  }
}

// Wrap approveText into 21-char lines; returns total line count. Fills buf if given.
int wrapText(const char* text, char buf[][22], int maxLines) {
  int line = 0, col = 0;
  for (int i = 0; text[i] && line < maxLines; i++) {
    if (text[i] == '\n' || col == 21) {
      if (buf) buf[line][col] = '\0';
      line++; col = 0;
      if (text[i] == '\n') continue;
    }
    if (line >= maxLines) break;
    if (buf) buf[line][col] = text[i];
    col++;
  }
  if (buf && line < maxLines) buf[line][col] = '\0';
  return (col > 0) ? line + 1 : line;
}

void drawDashboard() {
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 0);
  display.print("OPEN DECK");

  int pending = 0;
  for (int i = 0; i < 4; i++) if (slots[i].status == ST_BLOCKED) pending++;
  if (pending > 0) {
    char buf[12];
    snprintf(buf, sizeof(buf), "%d PENDING", pending);
    display.setCursor(128 - strlen(buf) * 6, 0);
    display.print(buf);
  }
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  for (int i = 0; i < 4; i++) {
    int y = 14 + i * 12;
    bool blocked = (slots[i].status == ST_BLOCKED);
    if (blocked) {
      display.fillRect(0, y - 2, 128, 11, SH110X_WHITE);
      display.setTextColor(SH110X_BLACK);
    } else {
      display.setTextColor(SH110X_WHITE);
    }

    // Show ctx% instead of elapsed once context is the thing worth knowing.
    char tail[8];
    if (slots[i].ctxPct >= 70) snprintf(tail, sizeof(tail), "c%u%%", slots[i].ctxPct);
    else                       fmtElapsed(slots[i].elapsed, tail, sizeof(tail));

    // Exactly 21 chars = 128px at 6px/char. The precision specifiers (.6/.5)
    // are load-bearing: plain %-6s pads to a MINIMUM width but won't truncate,
    // so a long agent name would run off the right edge of the panel.
    char row[24];
    snprintf(row, sizeof(row), "%c%d %-6.6s %-5.5s %5.5s",
             (i == selection) ? '>' : ' ',
             i + 1,
             slots[i].name,
             statusLabel(slots[i].status),
             tail);
    display.setCursor(0, y);
    display.print(row);
  }
}

void drawApprove() {
  display.setTextSize(1);

  // Header: inverted when the command matched a destructive pattern.
  if (approveDanger) {
    display.fillRect(0, 0, 128, 10, SH110X_WHITE);
    display.setTextColor(SH110X_BLACK);
    display.setCursor(0, 1);
    display.print("! APPROVE? ");
  } else {
    display.setTextColor(SH110X_WHITE);
    display.setCursor(0, 1);
    display.print("APPROVE? ");
  }
  display.print(approveAgent);
  if (approveCount > 1) {
    display.print(" 1/");
    display.print(approveCount);
  }

  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 13);
  char tool[22];
  snprintf(tool, sizeof(tool), "%.21s", approveTool);
  display.print(tool);

  static char lines[16][22];
  int total = wrapText(approveText, lines, 16);
  const int visible = 3;
  if (approveScroll > total - visible) approveScroll = max(0, total - visible);

  for (int i = 0; i < visible; i++) {
    int idx = approveScroll + i;
    if (idx >= total) break;
    display.setCursor(0, 24 + i * 9);
    display.print(lines[idx]);
  }

  // Reading is enforced by the interaction: no arming until you've scrolled
  // to the end of a command that doesn't fit on screen.
  if (total > visible && approveScroll < total - visible) {
    display.setCursor(120, 42);
    display.print("v");
  }

  display.drawLine(0, 53, 127, 53, SH110X_WHITE);
  display.setCursor(0, 56);
  if (!approveArmed)         display.print("SCROLL TO READ ALL");
  else if (approveConfirm)   display.print("! ENT AGAIN=CONFIRM");
  else                       display.print("ENT=yes  X=no");
}

void drawPalette() {
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 0);
  display.print("PALETTE");
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  if (paletteCount == 0) {
    display.setCursor(0, 26);
    display.print("(empty)");
    return;
  }

  const int visible = 5;
  int first = selection - visible / 2;
  if (first < 0) first = 0;
  if (first > paletteCount - visible) first = max(0, paletteCount - visible);

  for (int i = 0; i < visible; i++) {
    int idx = first + i;
    if (idx >= paletteCount) break;
    int y = 14 + i * 10;
    if (idx == selection) {
      display.fillRect(0, y - 1, 128, 10, SH110X_WHITE);
      display.setTextColor(SH110X_BLACK);
    } else {
      display.setTextColor(SH110X_WHITE);
    }
    display.setCursor(2, y);
    display.print(paletteItems[idx]);
  }
}

void drawFocus() {
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 0);
  char hdr[24];
  snprintf(hdr, sizeof(hdr), "%d %-8.8s %-5.5s", selection + 1,
           slots[selection].name, statusLabel(slots[selection].status));
  display.print(hdr);
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);
  for (int i = 0; i < 4; i++) {
    display.setCursor(0, 15 + i * 10);
    display.print(focusLines[i]);
  }
}

void drawAmbient() {
  // Minimal lit pixels: mono OLEDs burn in, and this screen may sit for hours.
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  int x = (millis() / 8000) % 90;      // drift to spread wear
  int y = 20 + ((millis() / 60000) % 3) * 8;
  display.setCursor(x, y);
  display.print("open deck");
}

void render() {
  display.clearDisplay();
  switch (mode) {
    case MODE_APPROVE:  drawApprove();   break;
    case MODE_PALETTE:  drawPalette();   break;
    case MODE_FOCUS:    drawFocus();     break;
    case MODE_AMBIENT:  drawAmbient();   break;
    default:            drawDashboard(); break;
  }
  // Attention signal: whole-frame invert, blinking while the alert is live.
  if (millis() < alertUntil && ((millis() / 200) % 2 == 0)) {
    display.invertDisplay(true);
  } else {
    display.invertDisplay(false);
  }
  display.display();
}

// ---------- host command parsing ----------
Status parseStatus(const String &s) {
  if (s == "run")     return ST_RUN;
  if (s == "blocked") return ST_BLOCKED;
  if (s == "done")    return ST_DONE;
  if (s == "error")   return ST_ERROR;
  return ST_IDLE;
}

String nextTok(const String &s, int &pos) {
  while (pos < (int)s.length() && s[pos] == ' ') pos++;
  int start = pos;
  while (pos < (int)s.length() && s[pos] != ' ') pos++;
  return s.substring(start, pos);
}

void handleCommand(const String &line) {
  int pos = 0;
  String cmd = nextTok(line, pos);

  if (cmd == "SLOT") {
    int n = nextTok(line, pos).toInt();
    if (n < 0 || n > 3) return;
    String name = nextTok(line, pos);
    String st   = nextTok(line, pos);
    uint32_t el = (uint32_t)nextTok(line, pos).toInt();
    uint8_t ctx = (uint8_t)nextTok(line, pos).toInt();
    strncpy(slots[n].name, name.c_str(), sizeof(slots[n].name) - 1);
    slots[n].name[sizeof(slots[n].name) - 1] = '\0';
    slots[n].status  = parseStatus(st);
    slots[n].elapsed = el;
    slots[n].ctxPct  = ctx;
    displayDirty = true;

  } else if (cmd == "APPROVE") {
    String agent = nextTok(line, pos);
    bool danger   = (nextTok(line, pos).toInt() != 0);
    String tool   = nextTok(line, pos);
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    String text = line.substring(pos);

    // The host re-pushes display state on a timer, so the same approval
    // arrives repeatedly. Re-applying it would restart the alert blink
    // forever AND reset the user's scroll position twice a second - which
    // would make a long command impossible to ever scroll through and arm.
    if (text == approveText && agent == approveAgent && tool == approveTool) {
      mode = MODE_APPROVE;
      return;
    }

    approveDanger = danger;
    strncpy(approveAgent, agent.c_str(), sizeof(approveAgent) - 1);
    approveAgent[sizeof(approveAgent) - 1] = '\0';
    strncpy(approveTool, tool.c_str(), sizeof(approveTool) - 1);
    approveTool[sizeof(approveTool) - 1] = '\0';
    strncpy(approveText, text.c_str(), sizeof(approveText) - 1);
    approveText[sizeof(approveText) - 1] = '\0';
    approveScroll  = 0;
    approveConfirm = false;
    // Armed immediately only if the whole command is already visible.
    approveArmed   = (wrapText(approveText, nullptr, 16) <= 3);
    mode = MODE_APPROVE;
    alertUntil = millis() + 1200;
    displayDirty = true;

  } else if (cmd == "APPROVE_COUNT") {
    // Kept separate from APPROVE on purpose: the queue depth changes whenever
    // another agent blocks, and folding it into the APPROVE line would make
    // every new queue entry look like a different request - resetting the
    // scroll position of the one the user is part-way through reading.
    int n = nextTok(line, pos).toInt();
    if (n != approveCount) { approveCount = n; displayDirty = true; }

  } else if (cmd == "APPROVE_CLEAR") {
    if (mode == MODE_APPROVE) mode = MODE_DASHBOARD;
    approveText[0] = '\0';
    displayDirty = true;

  } else if (cmd == "PALETTE_CLEAR") {
    paletteCount = 0;
    displayDirty = true;

  } else if (cmd == "PALETTE_ADD") {
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    if (paletteCount < PALETTE_MAX) {
      strncpy(paletteItems[paletteCount], line.substring(pos).c_str(), 21);
      paletteItems[paletteCount][21] = '\0';
      paletteCount++;
      displayDirty = true;
    }

  } else if (cmd == "FOCUS_LINE") {
    int n = nextTok(line, pos).toInt();
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    if (n >= 0 && n < 4) {
      strncpy(focusLines[n], line.substring(pos).c_str(), 21);
      focusLines[n][21] = '\0';
      displayDirty = true;
    }

  } else if (cmd == "MODE") {
    String m = nextTok(line, pos);
    if      (m == "DASHBOARD") mode = MODE_DASHBOARD;
    else if (m == "APPROVE")   mode = MODE_APPROVE;
    else if (m == "PALETTE") { mode = MODE_PALETTE; selection = 0; }
    else if (m == "FOCUS")     mode = MODE_FOCUS;
    else if (m == "AMBIENT")   mode = MODE_AMBIENT;
    displayDirty = true;

  } else if (cmd == "ALERT") {
    alertUntil = millis() + 1200;
    displayDirty = true;
  }
}

void pollHostSerial() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      buf.trim();
      if (buf.length()) handleCommand(buf);
      buf = "";
    } else if (c != '\r' && buf.length() < 400) {
      buf += c;
    }
  }
}

// ---------- input ----------
void handleEncoder(int8_t dir) {
  switch (mode) {
    case MODE_APPROVE: {
      int total = wrapText(approveText, nullptr, 16);
      approveScroll = constrain(approveScroll + dir, 0, max(0, total - 3));
      if (approveScroll >= total - 3) approveArmed = true;  // read to the end
      break;
    }
    case MODE_PALETTE:
      if (paletteCount) selection = constrain(selection + dir, 0, paletteCount - 1);
      break;
    default:
      selection = (selection + dir + 4) % 4;
      break;
  }
  displayDirty = true;
}

// Local UI reactions that must feel instant; the host still gets every event
// and owns the actual side effects (focus window, approve, inject keystroke).
bool enterSuppressed = false;

void handleKeyEvent(uint8_t idx, const char* edge) {
  bool isDown = (strcmp(edge, "DOWN") == 0);

  // Approve-mode gating on ENTER, applied BEFORE the event is emitted.
  // This has to swallow the event, not just skip the local handling: the host
  // acts on any EVT KEY_ENTER it receives, so emitting one while the command
  // is still unread would approve it anyway and make the "scroll to read" and
  // "confirm destructive" guards purely decorative.
  if (mode == MODE_APPROVE && isKey(idx, "KEY_ENTER")) {
    if (isDown) {
      if (!approveArmed) {                // not scrolled to the end yet
        enterSuppressed = true;
        displayDirty = true;
        return;
      }
      if (approveDanger && !approveConfirm) {
        approveConfirm = true;            // destructive: demand a second press
        enterSuppressed = true;
        displayDirty = true;
        return;
      }
      enterSuppressed = false;
    } else if (enterSuppressed) {
      if (strcmp(edge, "UP") == 0) enterSuppressed = false;
      return;                             // swallow UP/HOLD of a suppressed press
    }
  }

  emit(String("EVT ") + KEY_NAMES[idx] + " " + edge);

  if (!isDown) return;

  if (mode == MODE_APPROVE && isKey(idx, "KEY_CANCEL")) {
    approveConfirm = false;               // deny always works, never gated
  }

  if (mode == MODE_DASHBOARD || mode == MODE_FOCUS) {
    int slot = agentSlot(idx);
    if (slot >= 0) {
      selection = slot;
      displayDirty = true;
    }
  }
}

void scanMatrix() {
  for (uint8_t r = 0; r < 2; r++) {
    // Rows are OUTPUT_OPEN_DRAIN: LOW sinks, HIGH releases (never sources), so
    // two keys sharing a column across rows can't short one row into the other.
    digitalWrite(ROW_PINS[r], LOW);
    delayMicroseconds(20);

    for (uint8_t c = 0; c < 4; c++) {
      uint8_t idx = r * 4 + c;
      bool raw = !digitalRead(COL_PINS[c]);

      if (raw != keyRaw[idx]) {
        keyRaw[idx] = raw;
        keyChangeTime[idx] = millis();
      }
      if (millis() - keyChangeTime[idx] > DEBOUNCE_MS && keyState[idx] != keyRaw[idx]) {
        keyState[idx] = keyRaw[idx];
        if (keyState[idx]) {
          keyDownTime[idx]  = millis();
          keyHoldSent[idx]  = false;
          handleKeyEvent(idx, "DOWN");
        } else {
          handleKeyEvent(idx, "UP");
        }
      }
      if (keyState[idx] && !keyHoldSent[idx] && millis() - keyDownTime[idx] >= HOLD_MS) {
        keyHoldSent[idx] = true;
        handleKeyEvent(idx, "HOLD");
      }
    }
    digitalWrite(ROW_PINS[r], HIGH);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  pinMode(ENC_CLK_PIN, INPUT_PULLUP);
  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  for (uint8_t r = 0; r < 2; r++) {
    pinMode(ROW_PINS[r], OUTPUT_OPEN_DRAIN);
    digitalWrite(ROW_PINS[r], HIGH);
  }
  for (uint8_t c = 0; c < 4; c++) pinMode(COL_PINS[c], INPUT_PULLUP);

  for (int i = 0; i < 4; i++) {
    snprintf(slots[i].name, sizeof(slots[i].name), "--");
    slots[i].status = ST_IDLE;
    focusLines[i][0] = '\0';
  }

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed");
    while (1) delay(1000);
  }
  Serial.println("Open Deck ready");
  render();
}

unsigned long lastHeartbeat = 0;
unsigned long lastDraw = 0;
const unsigned long MIN_DRAW_MS = 15;

void loop() {
  int8_t dir = read_rotary();
  if (dir != 0) {
    emit(String("EVT ENCODER ") + (dir > 0 ? "+1" : "-1"));
    handleEncoder(dir);
  }

  scanMatrix();
  pollHostSerial();

  if (millis() - lastHeartbeat >= 1000) {
    lastHeartbeat = millis();
    emit(String("HB ") + millis());
  }

  // Alert blink and ambient drift need repaints with no input event behind them.
  if (millis() < alertUntil || mode == MODE_AMBIENT) displayDirty = true;

  if (displayDirty && millis() - lastDraw >= MIN_DRAW_MS) {
    render();
    displayDirty = false;
    lastDraw = millis();
  }

  delayMicroseconds(300);
}
