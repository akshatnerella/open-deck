// Grok Deck - Milestone 1: raw input test
// Board: Seeed XIAO ESP32S3, Arduino core

#define JOY_X_PIN   D0
#define JOY_Y_PIN   D1
#define JOY_SW_PIN  D2
#define ENC_A_PIN   D3
#define ENC_B_PIN   D6
#define ENC_SW_PIN  D7

volatile int encoderPos = 0;
volatile uint8_t lastEncoded = 0;

void IRAM_ATTR readEncoder() {
  int MSB = digitalRead(ENC_A_PIN);
  int LSB = digitalRead(ENC_B_PIN);
  int encoded = (MSB << 1) | LSB;
  int sum = (lastEncoded << 2) | encoded;

  if (sum == 0b1101 || sum == 0b0100 || sum == 0b0010 || sum == 0b1011) encoderPos++;
  if (sum == 0b1110 || sum == 0b0111 || sum == 0b0001 || sum == 0b1000) encoderPos--;

  lastEncoded = encoded;
}

void setup() {
  Serial.begin(115200);
  delay(1500); // let USB CDC enumerate

  pinMode(JOY_SW_PIN, INPUT_PULLUP);
  pinMode(ENC_A_PIN, INPUT_PULLUP);
  pinMode(ENC_B_PIN, INPUT_PULLUP);
  pinMode(ENC_SW_PIN, INPUT_PULLUP);

  attachInterrupt(digitalPinToInterrupt(ENC_A_PIN), readEncoder, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_B_PIN), readEncoder, CHANGE);

  Serial.println("Grok Deck - input test ready");
}

void loop() {
  int jx = analogRead(JOY_X_PIN);
  int jy = analogRead(JOY_Y_PIN);
  bool jsw = !digitalRead(JOY_SW_PIN);
  bool esw = !digitalRead(ENC_SW_PIN);

  Serial.printf("joy(%4d,%4d) sw:%d | enc:%4d encBtn:%d\n",
                jx, jy, jsw, encoderPos, esw);

  delay(100);
}
