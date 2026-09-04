// Battery validation: blink built-in LED, confirm it survives USB unplug
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_BUILTIN, LOW);   // ON (active-low)
  delay(500);
  digitalWrite(LED_BUILTIN, HIGH);  // OFF
  delay(500);
}
