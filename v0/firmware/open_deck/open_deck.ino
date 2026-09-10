// Open Deck firmware.
//
// Hardware: XIAO ESP32S3 | SH1106 128x64 mono OLED (I2C) | EC11 encoder
// (rotation only; the push-switch on this module is dead) | 8 keys, 2x4 matrix.
//
// The deck emits semantic input events and renders whatever state the host
// pushes back. It knows nothing about tmux or any agent harness.
//
// Device -> host:
//   EVT <KEY_NAME> DOWN|HOLD|UP
//   EVT ENCODER <+1|-1>
//   HB <uptime_ms>
// Host -> device:
//   STATE <idle|working|attention|done|active|asleep>
//   TOAST <text>

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <FluxGarage_RoboEyes.h>

#define OLED_ADDR    0x3C
#define SDA_PIN      D4
#define SCL_PIN      D5
#define ENC_CLK_PIN  D3
#define ENC_DATA_PIN D6

// Physical layout (index = row * 4 + col):
//   R1C1 TERM   R1C2 MIC     R1C3 FOX(1)  R1C4 PANDA(4)
//   R2C1 ENTER  R2C2 CANCEL  R2C3 CAT(3)  R2C4 OWL(2)
// Column order was verified by pressing R1C1..R2C4 in sequence and reading
// back what the device reported; it is the reverse of the wiring diagram.
const uint8_t ROW_PINS[2] = { D0, D1 };
const uint8_t COL_PINS[4] = { D7, D8, D9, D10 };

const char* KEY_NAMES[8] = {
  "KEY_TERM",  "KEY_MIC",    "KEY_AGENT1", "KEY_AGENT4",
  "KEY_ENTER", "KEY_CANCEL", "KEY_AGENT3", "KEY_AGENT2"
};

Adafruit_SH1106G display(128, 64, &Wire, -1);
RoboEyes<Adafruit_SH1106G> eyes(display);

// ---------- input ----------
bool keyState[8]    = {false};
bool keyRaw[8]      = {false};
bool keyHoldSent[8] = {false};
unsigned long keyChangeTime[8] = {0};
unsigned long keyDownTime[8]   = {0};
const unsigned long DEBOUNCE_MS = 25;
const unsigned long HOLD_MS     = 400;

static const int8_t ROT_TABLE[] = {0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0};
static uint8_t rotCode = 0;
static uint16_t rotStore = 0;

// ---------- face ----------
enum PixieState { PX_IDLE, PX_WORKING, PX_ATTENTION, PX_DONE, PX_ACTIVE, PX_ASLEEP };
PixieState pixieState = PX_IDLE;

char toastText[22] = "";
unsigned long toastUntil = 0;
bool toastDrawn = false;
const unsigned long TOAST_MS = 1800;

// plumber: rendering runs on the second core. A full SH1106 framebuffer flush
// blocks for ~29.5ms (measured), and RoboEyes wants a frame every 20ms - so on
// a single thread the display is saturated and readRotary() is never called
// during the flush. Encoder detents last only a few ms, so they were not
// arriving late, they were being dropped. Input now owns core 1 exclusively.
// Attention pulse: invertDisplay() is a single command byte, not a framebuffer
// write, so flashing costs nothing next to a ~29.5ms flush. A burst on entry
// catches the eye; a short repeat every 10s keeps a standing alert visible
// without being maddening.
int flashTicks = 0;
unsigned long flashNext = 0;
unsigned long lastPulse = 0;
const unsigned long FLASH_MS = 110;
const unsigned long PULSE_INTERVAL_MS = 10000;

portMUX_TYPE faceMux = portMUX_INITIALIZER_UNLOCKED;
volatile int sharedState = PX_IDLE;
volatile bool toastDirty = false;
char sharedToast[22] = "";

void emit(const String &line) {
  // ESP32-S3 native USB CDC blocks once its TX ring fills with no host
  // reading, which would stall the key scan and the face along with it.
  if (Serial.availableForWrite() >= (int)line.length() + 2) Serial.println(line);
}

int8_t readRotary() {
  rotCode <<= 2;
  if (digitalRead(ENC_DATA_PIN)) rotCode |= 0x02;
  if (digitalRead(ENC_CLK_PIN))  rotCode |= 0x01;
  rotCode &= 0x0f;
  if (ROT_TABLE[rotCode]) {
    rotStore = (rotStore << 4) | rotCode;
    if ((rotStore & 0xff) == 0x2b) return -1;
    if ((rotStore & 0xff) == 0x17) return 1;
  }
  return 0;
}

// Runs on the render core only.
void applyState(PixieState next) {
  if (next == pixieState) return;
  pixieState = next;

  // Moving straight between two moods' eyelid shapes leaves erase artifacts,
  // so settle through DEFAULT and let each transition be a smaller delta.
  eyes.setMood(DEFAULT);
  eyes.setCuriosity(false);
  eyes.setIdleMode(ON, 3, 2);
  eyes.setAutoblinker(ON, 3, 2);

  switch (next) {
    case PX_WORKING:
      eyes.setMood(DEFAULT);
      eyes.setCuriosity(true);
      break;
    case PX_ATTENTION:
      eyes.setMood(ANGRY);
      eyes.setIdleMode(OFF);
      eyes.setPosition(DEFAULT);
      flashTicks = 6;
      flashNext = 0;
      lastPulse = millis();
      break;
    case PX_DONE:
      eyes.setMood(HAPPY);
      eyes.anim_laugh();
      break;
    case PX_ACTIVE:
      eyes.setMood(DEFAULT);
      break;
    case PX_ASLEEP:
      eyes.setMood(TIRED);
      eyes.setIdleMode(OFF);
      eyes.setAutoblinker(ON, 6, 3);
      break;
    default:
      eyes.setMood(DEFAULT);
      break;
  }
}

PixieState parseState(const String &name) {
  if (name == "working")   return PX_WORKING;
  if (name == "attention") return PX_ATTENTION;
  if (name == "done")      return PX_DONE;
  if (name == "active")    return PX_ACTIVE;
  if (name == "asleep")    return PX_ASLEEP;
  return PX_IDLE;
}

void showToast(const String &text) {
  portENTER_CRITICAL(&faceMux);
  strncpy(sharedToast, text.c_str(), sizeof(sharedToast) - 1);
  sharedToast[sizeof(sharedToast) - 1] = '\0';
  toastDirty = true;
  portEXIT_CRITICAL(&faceMux);
}

// Toast text is static, so it is drawn and flushed once rather than every
// frame - the face resumes when it expires.
void drawToast() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  int width = strlen(toastText) * 6;
  int x = (128 - width) / 2;
  display.setCursor(x < 0 ? 0 : x, 28);
  display.print(toastText);
  display.drawFastHLine(0, 42, 128, SH110X_WHITE);
  display.display();
  toastDrawn = true;
}

String nextToken(const String &s, int &pos) {
  while (pos < (int)s.length() && s[pos] == ' ') pos++;
  int start = pos;
  while (pos < (int)s.length() && s[pos] != ' ') pos++;
  return s.substring(start, pos);
}

void handleCommand(const String &line) {
  int pos = 0;
  String cmd = nextToken(line, pos);

  if (cmd == "STATE") {
    sharedState = parseState(nextToken(line, pos));
  } else if (cmd == "TOAST") {
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    showToast(line.substring(pos));
  }
}

void pollHost() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      buf.trim();
      if (buf.length()) handleCommand(buf);
      buf = "";
    } else if (c != '\r' && buf.length() < 200) {
      buf += c;
    }
  }
}

void scanMatrix() {
  for (uint8_t r = 0; r < 2; r++) {
    // Rows are OUTPUT_OPEN_DRAIN: LOW sinks, HIGH releases rather than
    // sources, so two keys sharing a column across rows cannot short one
    // row's output into the other.
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
          keyDownTime[idx] = millis();
          keyHoldSent[idx] = false;
          emit(String("EVT ") + KEY_NAMES[idx] + " DOWN");
        } else {
          emit(String("EVT ") + KEY_NAMES[idx] + " UP");
        }
      }
      if (keyState[idx] && !keyHoldSent[idx] && millis() - keyDownTime[idx] >= HOLD_MS) {
        keyHoldSent[idx] = true;
        emit(String("EVT ") + KEY_NAMES[idx] + " HOLD");
      }
    }
    digitalWrite(ROW_PINS[r], HIGH);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  randomSeed(micros());

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  pinMode(ENC_CLK_PIN, INPUT_PULLUP);
  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  for (uint8_t r = 0; r < 2; r++) {
    pinMode(ROW_PINS[r], OUTPUT_OPEN_DRAIN);
    digitalWrite(ROW_PINS[r], HIGH);
  }
  for (uint8_t c = 0; c < 4; c++) pinMode(COL_PINS[c], INPUT_PULLUP);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed");
    while (1) delay(1000);
  }

  eyes.begin(128, 64, 50);
  eyes.setWidth(34, 34);
  eyes.setHeight(34, 34);
  eyes.setBorderradius(10, 10);
  eyes.setSpacebetween(12);
  eyes.setAutoblinker(ON, 3, 2);
  eyes.setIdleMode(ON, 3, 2);

  // Arduino's loopTask runs on core 1, so rendering goes to core 0.
  xTaskCreatePinnedToCore(renderTask, "render", 4096, nullptr, 1, nullptr, 0);

  Serial.println("Open Deck ready");
}

void renderTask(void *) {
  for (;;) {
    portENTER_CRITICAL(&faceMux);
    bool newToast = toastDirty;
    if (newToast) {
      strncpy(toastText, sharedToast, sizeof(toastText));
      toastDirty = false;
    }
    portEXIT_CRITICAL(&faceMux);

    if (newToast) {
      toastUntil = millis() + TOAST_MS;
      toastDrawn = false;
    }
    applyState(static_cast<PixieState>(sharedState));

    if (flashTicks > 0) {
      if (millis() >= flashNext) {
        display.invertDisplay(flashTicks % 2 == 0);
        flashNext = millis() + FLASH_MS;
        if (--flashTicks == 0) display.invertDisplay(false);
      }
    } else if (pixieState == PX_ATTENTION &&
               millis() - lastPulse >= PULSE_INTERVAL_MS) {
      lastPulse = millis();
      flashTicks = 2;
      flashNext = 0;
    }

    if (millis() < toastUntil) {
      if (!toastDrawn) drawToast();
      vTaskDelay(pdMS_TO_TICKS(20));
    } else {
      eyes.update();
      vTaskDelay(1);
    }
  }
}

unsigned long lastHeartbeat = 0;

void loop() {
  int8_t dir = readRotary();
  if (dir != 0) emit(String("EVT ENCODER ") + (dir > 0 ? "+1" : "-1"));

  scanMatrix();
  pollHost();

  if (millis() - lastHeartbeat >= 1000) {
    lastHeartbeat = millis();
    emit(String("HB ") + millis());
  }

  delayMicroseconds(200);
}
