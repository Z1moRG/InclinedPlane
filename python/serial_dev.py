import math
import time
import threading

"""
Symulator połączenia szeregowego.
Pozwala na pracę z GUI bez potrzeby korzystania z fizycznej płytki Arduino.
Symulator generuje odległość za pomocą funkcji logistycznej, co nie jest realistyczne, ale na potrzeby projektu starcza.
"""

def logistic(x, L = 1, k = 1, x0 = 0):
    return L / (1 + math.exp(-k * (x - x0)))

def distance(time, max_distance = 300, start_time = 0, end_time = 5000):
    if time < start_time:
        return 0
    if time > end_time:
        return max_distance
    return max_distance * logistic((time-start_time)/(end_time - start_time)*12, x0 = 6)

class SerialException(Exception):
    """Zachowuje się jak serial.SerialException."""
    pass

class Serial:
    def __init__(self, port, buad_rate, **kwargs):
        print(f"Symulacja portu szeregowego {port} z prędkością {buad_rate}")
        self.is_open = True
        self.lines = []
        self.current_time = 0
        self.last_update = time.time_ns()/1_000_000
        self.thread = threading.Thread(target=self.dev_update, daemon=True).start()

    @property
    def in_waiting(self):
        """Zwraca liczbę bajtów dostępnych do natychmiastowego odczytu w buforze."""
        if not self.is_open:
            raise SerialException("Serial port is closed.")
        return sum(len(line) for line in self.lines)

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        # Reset the timer for dev purposes
        self.current_time = 0
        self.lines = []

    def reset_output_buffer(self):
        pass

    def read_all(self):
        if not self.is_open:
            raise EOFError("Serial not open")
        result = bytes("\r\n".join(self.lines), "utf8")
        self.lines = []
        return result

    def readline(self):
        if not self.is_open:
            raise EOFError("Serial not open")
        while len(self.lines) == 0:
            pass
        result = bytes(self.lines[0], "utf8")
        self.lines = self.lines[1:]
        return result
    
    def dev_update(self):
        while True:
            current_time = time.time_ns()/1_000_000

            delta = current_time - self.last_update
            self.current_time += delta

            t = int(self.current_time)
            d = int(distance(self.current_time))
            btn_state = 0 # stale rozłączony '0'
            self.lines.append(f"{t},{d},{btn_state}\r\n")

            time.sleep(0.01)

            self.last_update = current_time