// Grok Deck - OLED test: render our terminal-badge logo
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "grok_logo_bitmap.h"

#define OLED_ADDR   0x3C  // confirmed via I2C scanner
#define SDA_PIN     D4
#define SCL_PIN     D5

Adafruit_SSD1306 display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin(SDA_PIN, SCL_PIN);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println("OLED init failed - check wiring/address");
    while (1) delay(1000);
  }

  Serial.println("OLED init OK, drawing logo");

  display.clearDisplay();
  // center the 64x64 logo on the 128x64 screen
  int x = (128 - LOGO_WIDTH) / 2;
  int y = (64 - LOGO_HEIGHT) / 2;
  display.drawBitmap(x, y, logo_bitmap, LOGO_WIDTH, LOGO_HEIGHT, SSD1306_WHITE);
  display.display();
}

void loop() {
  // static logo, nothing to update
}
