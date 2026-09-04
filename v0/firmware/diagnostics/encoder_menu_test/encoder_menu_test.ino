// Grok Deck - encoder menu scroll test
// Uses the well-known best-microcontroller-projects.com robust encoder
// algorithm: POLLED (not interrupt-driven - interrupts amplify bounce on
// noisy encoders), with two-stage validation (per-transition lookup table,
// then requiring two consecutive valid transitions to confirm one full
// detent) before counting a step.
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

#define OLED_ADDR   0x3C
#define SDA_PIN     D4
#define SCL_PIN     D5

#define ENC_DATA_PIN D6  // TRB
#define ENC_CLK_PIN  D3  // TRA
#define ENC_SW_PIN   D7  // PSH

Adafruit_SH1106G display(128, 64, &Wire, -1);

const char* menuItems[] = { "NONE", "LOW", "MEDIUM", "HIGH", "XHIGH" };
const int menuCount = 5;

static const int8_t rot_enc_table[] = {0,1,1,0,1,0,0,1,1,0,0,1,0,1,1,0};
static uint8_t prevNextCode = 0;
static uint16_t store = 0;

// Returns -1, 0, or +1 per call - call this frequently (polled, not ISR)
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

int menuIndex = 0;
int lastShownIndex = -1;

void drawMenu(int index) {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("REASONING EFFORT");
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  display.setTextSize(2);
  display.setCursor(10, 26);
  display.println(menuItems[index]);

  int dotSpacing = 20;
  int startX = (128 - (menuCount - 1) * dotSpacing) / 2;
  for (int i = 0; i < menuCount; i++) {
    int cx = startX + i * dotSpacing;
    if (i == index) {
      display.fillCircle(cx, 58, 3, SH110X_WHITE);
    } else {
      display.drawCircle(cx, 58, 2, SH110X_WHITE);
    }
  }

  display.display();
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  pinMode(ENC_CLK_PIN, INPUT_PULLUP);
  pinMode(ENC_SW_PIN, INPUT_PULLUP);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed");
    while (1) delay(1000);
  }

  Serial.println("Encoder menu test ready (polled, debounced)");
  drawMenu(0);
}

void loop() {
  int8_t dir = read_rotary();
  if (dir != 0) {
    menuIndex = ((menuIndex + dir) % menuCount + menuCount) % menuCount;
    Serial.printf("dir=%d -> index=%d -> %s\n", dir, menuIndex, menuItems[menuIndex]);
  }

  if (menuIndex != lastShownIndex) {
    drawMenu(menuIndex);
    lastShownIndex = menuIndex;
  }

  bool pressed = !digitalRead(ENC_SW_PIN);
  static bool wasPressed = false;
  static unsigned long lastButtonChange = 0;
  if (pressed != wasPressed && millis() - lastButtonChange > 50) {
    lastButtonChange = millis();
    wasPressed = pressed;
    if (pressed) Serial.println("Encoder button PRESSED");
  }

  delayMicroseconds(500); // tight polling interval for the encoder read
}
