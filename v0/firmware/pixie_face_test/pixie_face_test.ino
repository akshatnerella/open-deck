// Pixie on the Open Deck OLED.
//
// Pixie's face is drawn procedurally by FluxGarage RoboEyes, not played back
// from video - the same approach as the Pixie project's arduino/pixie_face,
// which uses the TFT port of this library on a 320x240 colour panel. Here it
// runs on the deck's 128x64 mono SH1106.
//
// RoboEyes defaults BGCOLOR=0 / MAINCOLOR=1, which are exactly
// SH110X_BLACK / SH110X_WHITE, so no colour mapping is needed.

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>
#include <FluxGarage_RoboEyes.h>

#define OLED_ADDR 0x3C
#define SDA_PIN   D4
#define SCL_PIN   D5

Adafruit_SH1106G display(128, 64, &Wire, -1);
RoboEyes<Adafruit_SH1106G> eyes(display);

// Pixie's emotion vocabulary, kept identical to the Pixie project so the
// character reads the same on both devices.
enum Emotion { NEUTRAL, HAPPY_E, EXCITED, SLEEPY, CONCERNED, CURIOUS };

const char* EMOTION_NAMES[] = {
  "neutral", "happy", "excited", "sleepy", "concerned", "curious"
};

void setEmotion(Emotion e) {
  // Jumping straight between two eyelid shapes leaves erase artifacts, so
  // settle through DEFAULT first and let each transition be a smaller delta.
  eyes.setMood(DEFAULT);
  eyes.setCuriosity(false);
  unsigned long settle = millis();
  while (millis() - settle < 250) eyes.update();

  switch (e) {
    case HAPPY_E:
      eyes.setMood(HAPPY);
      break;
    case EXCITED:
      eyes.setMood(HAPPY);
      eyes.anim_laugh();
      break;
    case SLEEPY:
      eyes.setMood(TIRED);
      break;
    case CONCERNED:
      eyes.setMood(ANGRY);
      break;
    case CURIOUS:
      // Curiosity only shows (a larger outer eye) while looking to a side.
      eyes.setCuriosity(true);
      eyes.setPosition(random(0, 2) ? E : W);
      break;
    default:
      eyes.setPosition(DEFAULT);
      break;
  }
  Serial.printf("emotion: %s\n", EMOTION_NAMES[e]);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  randomSeed(micros());

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  if (!display.begin(OLED_ADDR, true)) {
    Serial.println("SH1106 init failed");
    while (1) delay(1000);
  }

  eyes.begin(128, 64, 60);
  eyes.setWidth(34, 34);
  eyes.setHeight(34, 34);
  eyes.setBorderradius(10, 10);
  eyes.setSpacebetween(12);
  eyes.setAutoblinker(ON, 3, 2);
  eyes.setIdleMode(ON, 3, 2);

  Serial.println("Pixie ready");
}

unsigned long lastChange = 0;
const unsigned long HOLD_MS = 4000;
int current = 0;

void loop() {
  eyes.update();

  if (millis() - lastChange >= HOLD_MS) {
    lastChange = millis();
    current = (current + 1) % 6;
    setEmotion(static_cast<Emotion>(current));
  }
}
