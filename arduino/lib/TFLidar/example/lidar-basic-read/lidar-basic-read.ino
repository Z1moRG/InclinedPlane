// Библиотека для работы с дальномерами
#include "TFLidar.h"
 
// Библиотека для работы программного Serial
#include <SoftwareSerial.h>
 
// Serial-порт к которому подключён дальномер
#define LIDAR_SERIAL    mySerial
 
// Создаём объект для работы с программным Serial
// и передаём ему пины TX и RX
SoftwareSerial mySerial(10, 11);
// Создаём объект класса TFMiniPlus и передаём в него объект LIDAR_SERIAL 
TFLidar lidar;

// Переменная для хранения расстояния
int dist;

void setup() {
  // Открываем последовательный порт для мониторинга действий в программе
  // и передаём скорость 9600 бод
  Serial.begin(9600);
  // Ждём, пока не откроется монитор последовательного порта
  // для того, чтобы отследить все события в программе
  while (!Serial);
 
  Serial.print("Serial init OK\r\n");
  // Открываем Serial-соединение с дальномером на скорости 115200
  mySerial.begin(115200);
  lidar.begin(&LIDAR_SERIAL);    
}

void loop() {
  // Вычисляем расстояние до объекта
  lidar.getData(dist);
  // Выводим данные в Serial-порт
  Serial.print( "Dist: ");
  Serial.print(dist);
  Serial.print(" cm");
  Serial.println();
  // Ждём 50 мс
  delay(50);  
}
