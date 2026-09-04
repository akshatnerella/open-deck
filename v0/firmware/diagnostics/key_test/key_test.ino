// Grok Deck - single mechanical switch test
#define KEY_PIN D0

void setup() {
  Serial.begin(115200);
  delay(1500); // let USB CDC enumerate
  pinMode(KEY_PIN, INPUT_PULLUP);
  Serial.println("Key test ready");
}

void loop() {
  bool pressed = !digitalRead(KEY_PIN); // LOW when pressed (switch pulls pin to GND)
  Serial.println(pressed ? "PRESSED" : "released");
  delay(100);
}
