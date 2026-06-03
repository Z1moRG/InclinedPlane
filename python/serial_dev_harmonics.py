import math
import time
import threading
import random

"""
Moduł symulacyjny: serial_dev_harmonics.py
Kompatybilny z pyserial. Współpracuje z nową strukturą ramek danych (3 wartości).
Generuje pojedynczy układ drgań tłumionych z losową amplitudą i okresem.
Przez pierwsze 500 ms generuje płaską linię w położeniu równowagi.
"""

class SerialException(Exception):
    """Wyjątek symulujący oryginalny serial.SerialException."""
    pass

# Atrapa modułu narzędziowego list_ports dla funkcji find_arduino_port()
class DummyPort:
    def __init__(self):
        self.device = "some/path"
        self.description = "Arduino Virtual Dev Board (CH340)"

class ToolsListPorts:
    def comports(self):
        return [DummyPort()]

# Publikacja modułu wewnętrznego jako serial.tools.list_ports
import sys
from types import ModuleType
tools_module = ModuleType("serial.tools.list_ports")
tools_module.list_ports = ToolsListPorts()
sys.modules["serial.tools.list_ports"] = tools_module.list_ports

class Serial:
    def __init__(self, port, baud_rate, **kwargs):
        print(f"[Symulator] Inicjalizacja wirtualnego portu {port} ({baud_rate} bps)")
        self.is_open = True
        self.lines = []
        self.current_time = 0
        self.last_update = time.time_ns() / 1_000_000
        
        # Stałe fizyczne symulacji drgań
        self.equilibrium = 100  # Położenie równowagi w [cm]
        self.damping = 0.0002     # Współczynnik tłumienia
        
        # Losowanie parametrów z zadanych przedziałów
        self.amplitude = random.uniform(5.0, 100.0)
        self.period_ms = random.uniform(100.0, 1000.0)
        
        # Przeliczenie okresu T na częstość kołową omega
        period_sec = self.period_ms / 1000.0
        self.omega = (2 * math.pi) / period_sec
        
        print(f"[Symulator] Wylosowano -> Amplituda A: {self.amplitude:.2f}, Okres T: {self.period_ms:.2f} ms")

        # Uruchomienie wątku generowania danych pomiarowych
        self.thread = threading.Thread(target=self.dev_update, daemon=True)
        self.thread.start()

    @property
    def in_waiting(self):
        """Zwraca liczbę bajtów dostępnych do natychmiastowego odczytu w buforze."""
        if not self.is_open:
            raise SerialException("Serial port is closed.")
        return sum(len(line) for line in self.lines)

    def close(self):
        """Zamyka wirtualny port i zatrzymuje generowanie danych."""
        self.is_open = False

    def reset_input_buffer(self):
        """Resetuje bufor oraz losuje nowe parametry fizyczne dla kolejnego przejazdu."""
        self.amplitude = random.uniform(5.0, 100.0)
        self.period_ms = random.uniform(100.0, 1000.0)
        self.omega = (2 * math.pi) / (self.period_ms / 1000.0)
        
        print(f"[Symulator Nowiutki Przejazd] Amplituda A: {self.amplitude:.2f}, Okres T: {self.period_ms:.2f} ms")
        self.current_time = 0
        self.lines = []

    def reset_output_buffer(self):
        pass

    def read_all(self):
        """Odczytuje cały dostępny bufor."""
        if not self.is_open:
            raise SerialException("Serial port is closed.")
        result = bytes("".join(self.lines), "utf8")
        self.lines = []
        return result

    def readline(self):
        """Pobiera pojedynczą linię danych pomiarowych."""
        if not self.is_open:
            raise SerialException("Serial port is closed.")
        
        while len(self.lines) == 0:
            time.sleep(0.001)
            if not self.is_open:
                raise SerialException("Serial port closed during read operation.")
                
        result = bytes(self.lines[0], "utf8")
        self.lines = self.lines[1:]
        return result
    
    def dev_update(self):
        """Wątek generujący stan spoczynku (pierwsze 500 ms) oraz późniejszy ruch harmoniczny."""
        while self.is_open:
            current_time = time.time_ns() / 1_000_000
            delta = current_time - self.last_update
            self.current_time += delta
            self.last_update = current_time

            t = int(self.current_time)
            
            # Stan spoczynku przez pierwsze 500 ms eksperymentu
            if self.current_time < 500.0:
                d = int(self.equilibrium)
            else:
                # Odliczamy 500 ms od czasu całkowitego, aby faza cosinusa startowała poprawnie od zera
                t_osc_sec = (self.current_time - 500.0) / 1000.0
                decay = math.exp(-self.damping * (self.current_time - 500.0))
                oscillation = self.amplitude * decay * math.cos(self.omega * t_osc_sec)
                d = int(self.equilibrium + oscillation)
            
            # Symulacja stanu przycisku sprzętowego (np. stale rozłączony '0')
            btn_state = 0 

            # Formatowanie linii zawierające TRZY wartości oddzielone przecinkami (czas, dystans, przycisk)
            self.lines.append(f"{t},{d},{btn_state}\r\n")

            # Próbkowanie co 10 ms (częstotliwość około 100 Hz)
            time.sleep(0.01)
