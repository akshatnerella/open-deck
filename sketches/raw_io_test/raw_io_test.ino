// Open Deck - raw pin state diagnostic
// Prints live digitalRead() values every 300ms regardless of change,
// so we can see whether a pin is stuck HIGH (never pressed / not wired),
// stuck LOW (shorted / miswired), or actually toggling.

#define ENC_DATA_PIN D6  // DT
#define ENC_CLK_PIN  D3  // CLK
#define ENC_SW_PIN   D7  // SW (encoder push-button)

#define ROW0_PIN D0
#define COL0_PIN D9

void setup() {
  Serial.begin(115200);
  delay(1500);

  pinMode(ENC_DATA_PIN, INPUT_PULLUP);
  pinMode(ENC_CLK_PIN, INPUT_PULLUP);
  pinMode(ENC_SW_PIN, INPUT_PULLUP);

  pinMode(ROW0_PIN, OUTPUT);
  digitalWrite(ROW0_PIN, LOW);
  pinMode(COL0_PIN, INPUT_PULLUP);

  Serial.println("Raw IO test ready");
}

void loop() {
  Serial.printf(
    "CLK(D3)=%d DT(D6)=%d SW/D7=%d  |  COL0/D9=%d\n",
    digitalRead(ENC_CLK_PIN),
    digitalRead(ENC_DATA_PIN),
    digitalRead(ENC_SW_PIN),
    digitalRead(COL0_PIN)
  );
  delay(300);
}
