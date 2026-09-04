#include <Wire.h>

void setup() {
  Wire.begin(D4, D5); // SDA, SCL
  Serial.begin(115200);
  delay(1500);
  Serial.println("I2C scanner starting...");
}

void loop() {
  byte count = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Found device at 0x%02X\n", addr);
      count++;
    }
  }
  if (count == 0) Serial.println("No I2C devices found - check wiring");
  delay(3000);
}
