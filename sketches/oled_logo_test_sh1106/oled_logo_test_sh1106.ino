// Grok Deck - OLED test #2: try SH1106 driver instead of SSD1306
// (garbled/static look on SSD1306 driver is a classic symptom of
// this being an SH1106-controller module instead)
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include "grok_logo_bitmap.h"

#define OLED_ADDR   0x3C
#define SDA_PIN     D4
#define SCL_PIN     D5

Adafruit_SH1106G display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin(SDA_PIN, SCL_PIN);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed - check wiring/address");
    while (1) delay(1000);
  }

  Serial.println("SH1106 init OK, drawing logo");

  display.clearDisplay();
  int x = (128 - LOGO_WIDTH) / 2;
  int y = (64 - LOGO_HEIGHT) / 2;
  display.drawBitmap(x, y, logo_bitmap, LOGO_WIDTH, LOGO_HEIGHT, SH110X_WHITE);
  display.display();
}

void loop() {
  // static logo, nothing to update
}
