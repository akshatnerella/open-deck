// Open Deck - full validation test
// Exercises everything wired so far on one XIAO ESP32S3:
//   - 1.3" SH1106 OLED (I2C)
//   - EC11 rotary encoder + its push-switch (from the combo module)
//   - one key-matrix cell (row0/col0, through a diode) standing in for
//     the future 4x2 / 8-key matrix
//
// Encoder read algorithm is the polled, debounced lookup-table method
// from encoder_menu_test.ino (interrupts amplify bounce on noisy
// encoders, so this is intentionally NOT interrupt-driven).

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// --- Display ---
#define OLED_ADDR   0x3C
#define SDA_PIN     D4
#define SCL_PIN     D5
Adafruit_SH1106G display(128, 64, &Wire, -1);

// --- Encoder (from combo module) ---
// Push-switch dropped from scope (module's SW line tested dead / D7 free now)
#define ENC_DATA_PIN D6  // DT
#define ENC_CLK_PIN  D3  // CLK

// --- Key matrix cell under test: row0 -> diode -> switch -> col0 ---
#define ROW0_PIN D0   // driven LOW (this is the only row wired right now)
#define COL0_PIN D9   // INPUT_PULLUP, reads LOW when row0/col0 key is pressed

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

long encoderCount = 0;
bool keyPressed = false;

bool lastKey = false;
unsigned long lastKeyChange = 0;
const unsigned long DEBOUNCE_MS = 30;

void drawStatus() {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("OPEN DECK - VALIDATE");
  display.drawLine(0, 10, 127, 10, SH110X_WHITE);

  display.setCursor(0, 16);
  display.print("Encoder: ");
  display.println(encoderCount);

  display.setCursor(0, 30);
  display.print("Key R0C0: ");
  display.println(keyPressed ? "DOWN" : "up");

  display.display();
}

void setup() {
  Serial.begin(115200);
  delay(1500); // let USB CDC enumerate

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  pinMode(ENC_CLK_PIN, INPUT_PULLUP);

  pinMode(ROW0_PIN, OUTPUT);
  digitalWrite(ROW0_PIN, LOW);   // only row wired -> hold it active
  pinMode(COL0_PIN, INPUT_PULLUP);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed - check wiring/address");
    while (1) delay(1000);
  }

  Serial.println("Open Deck validate ready");
  drawStatus();
}

void loop() {
  bool dirty = false;

  // Encoder rotation
  int8_t dir = read_rotary();
  if (dir != 0) {
    encoderCount += dir;
    Serial.printf("encoder dir=%d count=%ld\n", dir, encoderCount);
    dirty = true;
  }

  // Key matrix cell (debounced)
  bool rawKey = !digitalRead(COL0_PIN);
  if (rawKey != lastKey && millis() - lastKeyChange > DEBOUNCE_MS) {
    lastKeyChange = millis();
    lastKey = rawKey;
    keyPressed = rawKey;
    Serial.println(keyPressed ? "KEY R0C0 DOWN" : "key r0c0 up");
    dirty = true;
  }

  if (dirty) drawStatus();

  delayMicroseconds(500); // tight polling interval for the encoder read
}
