#include "TFLidar.h"
#include <SoftwareSerial.h>

// green wire (lidar sensor) - pin 10
// white wire (lidar sensor) - pin 11
// red wire (lidar sensor) - 5V
// black wire (lidar sensor) - GND

#define LIDAR_SERIAL mySerial
#define PIN_BTN 4

SoftwareSerial mySerial(10, 11);
TFLidar lidar;

int16_t distance;
bool released = false;
unsigned long previousMillis = 0;

// --- Zmienne do bezblokadowego debouncingu przycisku ---
int lastButtonState = HIGH;     // Poprzedni odczyt z pinu (INPUT_PULLUP domyślnie daje HIGH)
int stableButtonState = HIGH;   // Ostateczny, odfiltrowany stan przycisku
unsigned long lastDebounceTime = 0;  // Znacznik czasu ostatniego drgnięcia styków
const unsigned long debounceDelay = 20; // Czas filtracji styków w milisekundach


void setup()
{
  Serial.begin(115200);
  while (!Serial);
 
  Serial.print("Serial init OK\r\n");
  mySerial.begin(115200);
  lidar.begin(&LIDAR_SERIAL);    

  pinMode(PIN_BTN, INPUT_PULLUP);
}

void loop()
{
  lidar.getData(distance); 

  int currentReading = digitalRead(PIN_BTN);
  if (currentReading != lastButtonState) {
    lastDebounceTime = millis();
  }
  // Dopiero gdy stan pinu jest stabilny przez ponad debounceDelay, uznajemy zmianę za prawdziwą
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (currentReading != stableButtonState) {
      stableButtonState = currentReading;
    }
  }
  lastButtonState = currentReading;

  if (distance < 600) 
  {
    Serial.print(millis());
    Serial.print(",");
    Serial.print(distance);
    Serial.print(",");
    // Wysyłamy odfiltrowany stan: 1 = puszczony (HIGH), 0 = wciśnięty (LOW)
    Serial.println(stableButtonState == HIGH ? 1 : 0);
  }
}
