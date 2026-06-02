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
  released = digitalRead(PIN_BTN);

  if (released)
  {
    lidar.getData(distance); 
    if (distance < 600) // lidars have an indoor range of 12m, an outdoor range of 7m 
    {
      Serial.print(millis() - previousMillis);
      Serial.print(",");
      Serial.println(distance);
    }
  }
  else
  {
    previousMillis = millis();
  }
}
