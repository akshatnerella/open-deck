// Open Deck - full 8-key matrix + encoder + OLED status firmware
//
// Only row0/col0 (the "Terminal" key) is physically wired right now —
// the rest of the matrix will just read "up" until the other 7 keys
// and the rest of the case are wired in. Scan logic is written for the
// full matrix so nothing needs to change firmware-side once they're
// connected; just start printing more DOWN events for those keys.
//
// Key layout: physical 2 rows x 4 cols (matches the case layout).
//   row D0: R1C1 Terminal  R1C2 Enter(check)  R1C3 Fox   R1C4 Owl
//   row D1: R2C1 Voice(mic) R2C2 Cancel(X)    R2C3 Cat   R2C4 Panda
// Cols in pin order: C1=D10 C2=D9 C3=D8 C4=D7
// (D2 = GPIO3, an ESP32-S3 strapping pin - avoided here since a switch
// sitting on it could interfere with boot-mode sensing if pressed right
// at power-on. D7 = GPIO44, plain GPIO, no such risk.)
//
// Only R1C1 has a diode (first key wired, before we decided the rest of
// the matrix doesn't need them - no simultaneous-chord functionality
// planned, so ghosting risk is negligible for a macro pad). All other
// 7 keys are wired switch-only, straight from row pin to col pin.
//
// Encoder push-switch dropped from scope (dead on this module, confirmed
// via raw_io_test.ino) - D7 is free for future use.

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// --- Display ---
#define OLED_ADDR   0x3C
#define SDA_PIN     D4
#define SCL_PIN     D5
Adafruit_SH1106G display(128, 64, &Wire, -1);

// --- Encoder ---
#define ENC_DATA_PIN D6  // DT
#define ENC_CLK_PIN  D3  // CLK

// --- Key matrix: 2 rows x 4 cols = 8 keys ---
const uint8_t ROW_PINS[2] = { D0, D1 };
const uint8_t COL_PINS[4] = { D10, D9, D8, D7 };

// row-major: idx = row*4 + col
const char* KEY_NAMES[8] = {
  "TERM", "ENTR", "FOX", "OWL",   // row D0 (R1C1..R1C4)
  "MIC",  "X",    "CAT", "PNDA"  // row D1 (R2C1..R2C4) - "PNDA" so it fits the 30px box (4 chars max at 6px/char)
};

bool keyState[8]       = { false, false, false, false, false, false, false, false };
bool keyStateRaw[8]    = { false, false, false, false, false, false, false, false };
unsigned long keyChangeTime[8] = { 0 };
const unsigned long DEBOUNCE_MS = 25;

// --- Encoder read (polled, debounced lookup-table method) ---
static const int8_t rot_enc_table[] = {0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0};
static uint8_t prevNextCode = 0;
static uint16_t store = 0;

int8_t read_rotary() {
  prevNextCode <<= 2;
  if (digitalRead(ENC_DATA_PIN)) prevNextCode |= 0x02;
  if (digitalRead(ENC_CLK_PIN))  prevNextCode |= 0x01;
  prevNextCode &= 0x0f;

  if (rot_enc_table[prevNextCode]) {
    store <<= 4;
    store |= prevNextCode;
    if ((store & 0xff) == 0x2b) return -1;
    if ((store & 0xff) == 0x17) return 1;
  }
  return 0;
}

// ESP32-S3's native USB CDC Serial blocks on write once its internal TX
// ring buffer fills, if nothing on the host side is actively draining it
// (unlike a classic USB-UART bridge chip, which just drops bytes). Since
// these prints happen inline in loop(), a blocked write would stall the
// matrix scan AND the display push right along with it - so never print
// unless there's room, drop the line instead of blocking.
void serialPrintlnSafe(const String &line) {
  if (Serial.availableForWrite() >= (int)line.length() + 2) {
    Serial.println(line);
  }
}

long encoderCount = 0;

bool displayDirty = true; // start true so the initial grid gets drawn

void scanMatrix() {
  for (uint8_t r = 0; r < 2; r++) {
    // rows are OUTPUT_OPEN_DRAIN (set once in setup()): driving LOW still
    // actively sinks the active row, but driving HIGH just releases the
    // pin to float instead of sourcing current - same short-circuit
    // protection as a true Hi-Z idle row (two keys sharing a column
    // across different rows can't short one row's drive into another's),
    // but with plain fast digitalWrite() instead of pinMode() every scan.
    digitalWrite(ROW_PINS[r], LOW);
    delayMicroseconds(20); // let the line settle before reading

    for (uint8_t c = 0; c < 4; c++) {
      uint8_t idx = r * 4 + c;
      bool raw = !digitalRead(COL_PINS[c]); // LOW = pressed (row driven low, switch pulls col low)

      if (raw != keyStateRaw[idx]) {
        keyStateRaw[idx] = raw;
        keyChangeTime[idx] = millis();
      }
      if (millis() - keyChangeTime[idx] > DEBOUNCE_MS && keyState[idx] != keyStateRaw[idx]) {
        keyState[idx] = keyStateRaw[idx];
        serialPrintlnSafe(String("KEY ") + KEY_NAMES[idx] + " " + (keyState[idx] ? "DOWN" : "up"));
        displayDirty = true;
      }
    }

    digitalWrite(ROW_PINS[r], HIGH); // release (open-drain HIGH = floating, not driven)
  }
}

void drawStatus() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("OPEN DECK  enc:");
  display.println(encoderCount);
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  // 2x4 grid of key boxes mirroring the physical layout
  const int boxW = 30, boxH = 24, gapX = 2, gapY = 2, originX = 2, originY = 14;
  for (uint8_t r = 0; r < 2; r++) {
    for (uint8_t c = 0; c < 4; c++) {
      uint8_t idx = r * 4 + c;
      int x = originX + c * (boxW + gapX);
      int y = originY + r * (boxH + gapY);
      if (keyState[idx]) {
        display.fillRect(x, y, boxW, boxH, SH110X_WHITE);
        display.setTextColor(SH110X_BLACK);
      } else {
        display.drawRect(x, y, boxW, boxH, SH110X_WHITE);
        display.setTextColor(SH110X_WHITE);
      }
      display.setCursor(x + 3, y + 7);
      display.print(KEY_NAMES[idx]);
    }
  }
  display.display();
}

void setup() {
  Serial.begin(115200);
  delay(1500);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  pinMode(ENC_CLK_PIN, INPUT_PULLUP);

  for (uint8_t r = 0; r < 2; r++) {
    pinMode(ROW_PINS[r], OUTPUT_OPEN_DRAIN);
    digitalWrite(ROW_PINS[r], HIGH); // idle = released/floating, not driven (see scanMatrix())
  }
  for (uint8_t c = 0; c < 4; c++) {
    pinMode(COL_PINS[c], INPUT_PULLUP);
  }

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed - check wiring/address");
    while (1) delay(1000);
  }

  Serial.println("Open Deck matrix firmware ready");
  drawStatus();
}

unsigned long lastDraw = 0;
const unsigned long MIN_DRAW_INTERVAL_MS = 15; // coalesce fast encoder spins into fewer I2C pushes

void loop() {
  int8_t dir = read_rotary();
  if (dir != 0) {
    encoderCount += dir;
    serialPrintlnSafe(String("encoder dir=") + dir + " count=" + encoderCount);
    displayDirty = true;
  }

  scanMatrix(); // sets displayDirty itself on any debounced key edge

  // only push the ~30-80ms I2C frame when something actually changed -
  // redrawing on a blind timer was hammering the SH1106 with full-frame
  // refreshes ~30x/sec regardless of activity, which starved loop() and
  // made both the encoder and the visible display update feel laggy.
  if (displayDirty && millis() - lastDraw >= MIN_DRAW_INTERVAL_MS) {
    drawStatus();
    displayDirty = false;
    lastDraw = millis();
  }

  delayMicroseconds(300); // keep encoder polling tight
}
