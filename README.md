# InclinedPlane – Real-Time Distance Measuring & Analytics System

An integrated hardware-software system designed for real-time kinematic and dynamic motion analysis in physics laboratory environments (e.g., inclined planes, harmonic oscillators). 

The system utilizes a high-frequency **TF-Mini LiDAR (Time-of-Flight)** laser sensor paired with an **Arduino** microcontroller to stream distance data to a custom **Python 3 GUI application** for real-time visualization, noise filtering, and multi-run comparison.

---

## Key Features

*   **Real-Time Visualization:** Renders precise Distance vs. Time plots with up to 100Hz refresh rate using a non-blocking architecture.
*   **Dual-Trigger Mechanics:** Measurements can be triggered programmatically via GUI or via a physical hardware button mounted on the track.
*   **Hardware-Software Sync:** Employs an aggressive 100ms hardware buffer purge mechanism (`read_all`) combined with delayed phase synchronization (\(t_0\)).
*   **Non-Blocking Button Debouncing:** Arduino firmware filters button contacts using time-based debouncing (`millis()`) instead of processor-blocking delays, ensuring zero lidar data drops.
*   **Data Aggregation:** Uses a time-windowed block averaging filter to eliminate high-frequency sensor jitter and decimate points for optimized GUI rendering.
*   **Multi-Run Interactive Comparison:** 
    *   **Align to (0,0):** Automatically overlaps multiple runs mathematically to visually analyze acceleration and rates of change.
    *   **Drag-and-Drop Adjustment:** Move any selected curve along the X and Y axes using the left mouse button to compensate for human reaction delays.
    *   **Dynamic Indicators:** The plot legend dynamically transforms into a live indicator displaying X and Y offsets (\(\Delta t\) and \(\Delta d\)) during manual alignment.
*   **Configurable Timeout:** Allows users to manually set the measurement duration via the GUI, backed by a fail-safe computer system timer.

---

## Project Structure

```text
InclinedPlane
├─ LICENSE
├─ README.md
├─ arduino
│  ├─ doc/                 # Hardware schematics and component documentation
│  ├─ lib/TFLidar/         # Custom low-level driver library for the LiDAR sensor
│  └─ src/main.cpp         # Arduino firmware with non-blocking debouncing & 3-column telemetry
├─ instructions
│  ├─ dokumentacja_projektu.tex   # Comprehensive report source file in LaTeX
│  └─ dokumentacja_projektu.pdf   # Compiled, print-ready laboratory guide
└─ python
   ├─ distance_monitor.py              # Baseline plotting and serial interface script
   ├─ distance_monitor_with_button.py  # Fully featured production GUI app (Drag & Drop, Timeout)
   ├─ distance_monitor_low_latency_with_button.py   # Production GUI app optimized for Windows OS; utilizes a cascade buffer-flushing loop to eliminate serial latency without any data loss or curve distortion
   └─ serial_dev.py                    # Virtual serial port emulator for offline development
```

---

## Hardware Configuration

*   **Microcontroller:** Arduino Uno / Mega / Nano (or compatible clone with CH340).
*   **Sensor:** Benewake TF-Mini LiDAR (ToF).
    *   *(Green) wire (TX)* $\rightarrow$ Arduino Pin 10 (SoftwareSerial RX)
    *   *(White) wire (RX)* $\rightarrow$ Arduino Pin 11 (SoftwareSerial TX)
    *   *(Red) wire* $\rightarrow$ 5V
    *   *(Black) wire* $\rightarrow$ GND
*   **Physical Button:** Connected between Arduino Pin 12 and GND (`INPUT_PULLUP`).

---

## Getting Started

### 1. Flashing the Hardware
1. Connect the Arduino to your computer via USB.
2. Ensure the custom `TFLidar` library from `arduino/lib/` is included in your Arduino environment.
3. Open `arduino/src/main.cpp`, configure the port, and upload the code to the board.

### 2. Running the Python GUI App
Make sure Python 3 and the necessary libraries are installed:
```bash
pip install pyserial matplotlib tkinter
```
Run the primary production script:
```bash
python python/distance_monitor_with_button.py
```

