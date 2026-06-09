DEV_MODE = False # przekazuje fikcyjną ścieżkę do wirtualnego modułu symulacyjnego (dla testów bez płytki arduino)
DEV_LM = False # wymusza ścieżkę /dev/ttyACM0 (ustaw ręcznie ścieżkę gdy find_arduino_port() nie jest wstanie znaleźć portu z płtyką Arduino)

if DEV_MODE:
    import serial_dev as serial
else:
    import serial
    import serial.tools.list_ports

import matplotlib.pyplot as plt
import threading
import tkinter as tk
from tkinter import messagebox, filedialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
from matplotlib.widgets import Cursor
import time

# === CONFIGURATION ===
TIME = 60000   # Duration of measurement timeout in ms
AGGR = 10      # Aggregation window in ms
BAUD_RATE = 115200

def find_arduino_port():
    """Funkcja realizuje inspekcję sprzętową magistrali USB komputera w celu autonomicznej identyfikacji 
    podłączonego mikrokontrolera (szuka portu z Arduino)."""
    try:
        ports = serial.tools.list_ports.comports()
        if not ports:
            raise Exception("No serial ports detected.\n\n"
                            "Make sure your Arduino is connected.")

        # "Arduino": Wykrywa oryginalne płytki deweloperskie.
        # "CH340": Wykrywa popularne, budżetowe klony Arduino wyposażone w układ scalony konwertera CH340/CH341.
        # "USB": Stanowi uniwersalny filtr dla generycznych konwerterów FTDI/CP2102 (system operacyjny często nazywa je po prostu "USB Serial Port").
        for port in ports:
            print(f"Checking port: {port.device} ({port.description})")
            if "Arduino" in port.description or "CH340" in port.description or "USB" in port.description:
                print(f"Arduino detected on port: {port.device}")
                return port.device

        raise Exception("Arduino not found.\n\n"
                        "Make sure the board is connected and drivers are installed.")
    except Exception as e:
        messagebox.showerror("Arduino Connection Error", str(e))
        exit(1)


if DEV_MODE:
    SERIAL_PORT = "some/path"
elif DEV_LM:
    SERIAL_PORT = "/dev/ttyACM0"
else:
    SERIAL_PORT = find_arduino_port()

def aggregate_data(times, distances):
    """Algorytm okienkowego uśredniania danych - działa jak filtr dolnoprzepustowy (redukuje szum o wysokiej częstotliwości) 
    oraz algorytm decymacji (zmniejsza liczbę punktów na wykresie bez utraty kluczowych informacji fizycznych, takich jak kształt paraboli)."""
    
    # zapobiega IndexError
    if not times:
        return [], []

    aggregated_times = []
    aggregated_distances = []

    current_time = times[0] # wyznacza lewą (początkową) krawędź aktualnego okna czasowego
    sum_distance = 0 # suma odległości w oknie
    count = 0 # licznik pomiarów (czas, odległość) w oknie

    for t, d in zip(times, distances):
        if t - current_time <= AGGR:
            sum_distance += d
            count += 1
        else:
            aggregated_times.append(current_time + AGGR // 2) # środek okna czasowego
            aggregated_distances.append(sum_distance / count) # średnia arytmetyczna odległości w tym oknie

            current_time = t
            sum_distance = d
            count = 1

    # Po wyjściu z pętli for, w pamięci podręcznej podręcznej (zmiennych sum_distance i count) 
    # pozostają dane z ostatniego, niedokończonego okna - ich ostateczne uśrednienie i dodanie do list wynikowych
    aggregated_times.append(current_time + AGGR // 2)
    aggregated_distances.append(sum_distance / count)

    return aggregated_times, aggregated_distances
    # UWAGA: Jeśli między dwoma pomiarami nastąpi długa przerwa (np. brak danych przez czas większy niż 2 * AGGR), 
    # algorytm potraktuje kolejny punkt jako "nowe okno tuż obok starego" i sztucznie przypisze mu czas przesunięty 
    # tylko o AGGR // 2 od momentu jego wystąpienia, zamiast zachować realną, pustą przerwę w osi czasu.

# === GUI CLASS ===
class DistanceApp:
    """Główny kontroler aplikacji (wzorzec architektoniczny zbliżony do MVC – Model-View-Controller)."""

    def __init__(self, root):
        
        # --- Główne okno aplikacji (Tkinter) ---
        self.root = root 
        self.root.title("Distance Measuring System")
        self.line_colors = iter(['b', 'g', 'r', 'c', 'm', 'y', 'k']) # iterator kolorków (niebieski, zielony, czerwony itd.). Każdy nowy wykres/pomiar dostanie automatycznie kolejny kolor z listy

        # --- Zmienne kontrolne ---
        self.plotting = False       # czy pomiar aktualnie trwa (zapobiega jednoczesnemu uruchomieniu kilku wątków pomiarowych)
        self.stop_requested = False # czy użytkownik zażądał zatrzymania pomiaru
        self.current_line = None    # referencja do aktualnie modyfikowanego obiektu linii

        self.root.protocol("WM_DELETE_WINDOW", self.quit_app) # gdy użytkownik klika "X" w prawym górnym rogu okna wywoła funkcję zamykania self.quit_app

        # --- Tworzenie wykresu Matplotlib ---
        self.plot_frame = tk.Frame(root)                # tworzy w oknie specjalny kontener (ramkę) przeznaczoną wyłącznie na wykres
        self.plot_frame.pack(fill=tk.BOTH, expand=True) # ramka rozciąga się na całe dostępne okno

        # Inicjalizacja standardowego wykres Matplotlib 
        self.fig, self.ax = plt.subplots() 
        self.ax.set_xlabel('Time [ms]')
        self.ax.set_ylabel('Distance [cm]')
        self.ax.set_title('Distance vs Time')
        self.ax.grid(True)

        self.cursor = Cursor(self.ax, useblit=True, color='red', linewidth=1)   # tworzy czerwony celownik
        self.fig.canvas.mpl_connect('scroll_event', self.change_scale)          # podpina rolkę myszy do skalowania wykresu

        # --- Zmienne do manualnego przesuwania wykresów myszką ---
        self.selected_line = None   # Referencja do wybranej linii
        self.line_offsets = {}      # Przesunięcia w osi X [obiekt_linii] = całkowity_offset_x
        self.line_offsets_y = {}    # Przesunięcia w osi Y [obiekt_linii] = całkowity_offset_y
        self.is_dragging = False    # Flaga informująca, czy trwa przeciąganie
        self.press_x = None         # Pozycja X myszy w momencie kliknięcia
        self.press_y = None         # Pozycja Y myszy w momencie kliknięcia

        # --- Powiązanie zdarzeń myszy Matplotlib ---
        self.fig.canvas.mpl_connect('pick_event', self.on_line_pick)                # kliknięcie w linię wykresu
        self.fig.canvas.mpl_connect('motion_notify_event', self.on_line_drag)       # przeciąganie linii wykresu
        self.fig.canvas.mpl_connect('button_release_event', self.on_line_release)   # puszczenie przycisku myszy
        
        # --- Powiązanie Matplotlib z Tkinterem ---
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame) # zamienia wykres Matplotlib w element interfejsu Tkintera
        self.canvas.draw() # pierwsze renderowanie (narysowanie) wykresu 
        # get_tk_widget() wyciąga gotowy widżet
        # Sam wykres Matplotlib nie potrafi wyświetlić się w Tkinterze. 
        # Ta metoda zwraca obiekt, który Tkinter rozumie i traktuje jak zwykły element okna.
        self.canvas_widget = self.canvas.get_tk_widget() 
        # Dopiero teraz, gdy mamy obiekt w formacie Tkintera, możemy użyć metody .pack(), aby fizycznie przypiąć (wyświetlić) wykres na ekranie użytkownika.
        self.canvas_widget.pack(fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_frame) # dodaje pod wykresem standardowy pasek narzędziowy Matplotlib (ikonki lupy, dyskietki do zapisu, przesuwania rączką itp.)
        self.toolbar.update() # synchronizuje pasek z wykresem
        self.toolbar.pack(fill=tk.X) # rozciąga pasek narzędziowy idealnie w poziomie na całą szerokość ramki

        btn_frame = tk.Frame(root) # nowa, niezależna ramka na samym dole okna głównego
        btn_frame.pack(pady=10) # odstęp pionowy

        # --- Kontrolka ręcznego ustawiania czasu trwania pomiaru ---
        self.time_label = tk.Label(btn_frame, text="Timeout [ms]:")
        self.time_label.grid(row=0, column=7, padx=5)

        # Tworzymy pole tekstowe powiązane ze zmienną Tkintera (domyślnie TIME ms)
        # Ta zmienna działa jak "żywy most" - każda zmiana wpisana przez użytkownika w okienku 
        # od razu zaktualizuje wartość w tej zmiennej, skąd łatwo ją potem pobrać w kodzie.
        self.time_var = tk.StringVar(value=f"{TIME}")
        self.time_entry = tk.Entry(btn_frame, textvariable=self.time_var, width=10)
        self.time_entry.grid(row=0, column=8, padx=5)

        # --- Przyciski i inne widżety ---

        # Przyciski Start
        self.start_btn = tk.Button(
            btn_frame,
            text="Start Measurement",
            command=self.start_measurement
        )
        self.start_btn.grid(row=0, column=0, padx=10)

        # Przyciski Cease (stop)
        self.cease_btn = tk.Button(
            btn_frame,
            text="Cease Measurement",
            command=self.cease_measurement,
            state=tk.DISABLED # domyślnie zablokowany - zostanie aktywowany programowo dopiero po kliknięciu "Start measurement"
        )
        self.cease_btn.grid(row=0, column=1, padx=10)

        # Checkbox Autoscroll
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.scroll_check = tk.Checkbutton(
            btn_frame, 
            text="Auto-scroll", 
            variable=self.autoscroll_var,
            command=self.toggle_autoscroll 
        )
        self.scroll_check.grid(row=0, column=5, padx=10)

        # Checkbox Align to (0,0)
        # Zmienna dla wyrównywania wykresów do punktu zero
        self.align_zero_var = tk.BooleanVar(value=False)
        self.align_check = tk.Checkbutton(
            btn_frame, 
            text="Align to (0,0)", 
            variable=self.align_zero_var
        )
        self.align_check.grid(row=0, column=6, padx=10) 

        # Przycisk "Clear Plot"
        self.clear_btn = tk.Button(btn_frame, text="Clear Plot", command=self.clear_plot)
        self.clear_btn.grid(row=0, column=2, padx=10)

        # Przycisk "Save Plot"
        self.save_btn = tk.Button(btn_frame, text="Save Plot", command=self.save_plot)
        self.save_btn.grid(row=0, column=3, padx=10)

        # Przycisk "Quit"
        self.quit_btn = tk.Button(btn_frame, text="Quit", command=self.quit_app)
        self.quit_btn.grid(row=0, column=4, padx=10)

        self.fig.canvas.mpl_connect('button_press_event', self.on_bg_click) 
        # Nasłuchuje kliknięć myszy w dowolnym miejscu wykresu. Jeśli użytkownik miał zaznaczoną linię (do przesuwania) i kliknie w puste tło, funkcja on_bg_click odznaczy tę linię.

    
    def start_measurement(self):
        if self.plotting:
            messagebox.showinfo("Measurement", "Measurement already running.")
            return
        
        # NOWE: Walidacja wprowadzonego czasu trwania pomiaru 
        try:
            user_time = int(self.time_var.get())
            if user_time <= 0:
                raise ValueError
            self.current_timeout = user_time  # Zapisujemy poprawną wartość do użycia w wątku
        except ValueError:
            messagebox.showerror("Błąd konfiguracji", "Wprowadź poprawną, dodatnią liczbę milisekund (np. 10000)!")
            return

        self.plotting = True
        self.stop_requested = False

        self.start_btn.config(state=tk.DISABLED)
        self.cease_btn.config(state=tk.NORMAL)
        self.clear_btn.config(state=tk.DISABLED)  # <-- BLOKADA CZYSZCZENIA
        self.time_entry.config(state=tk.DISABLED)  # <-- Blokada pola tekstowego podczas pomiaru

        # UTWORZENIE NOWEJ LINII DLA TEGO POMIARU
        try:
            color = next(self.line_colors)
        except StopIteration:
            self.line_colors = iter(['b', 'g', 'r', 'c', 'm', 'y', 'k'])
            color = next(self.line_colors)

        self.current_line, = self.ax.plot([], [], color=color, label=f"Run {color}", picker=5)
        self.line_offsets[self.current_line] = 0.0  
        self.line_offsets_y[self.current_line] = 0.0  # <-- NOWE
        self.ax.legend()

        threading.Thread(target=self.update_plot, daemon=True).start()

    def cease_measurement(self):
        self.stop_requested = True
        self.cease_btn.config(state=tk.DISABLED)

    def toggle_autoscroll(self):
        """Resetuje tryb nawigacji toolbara, jeśli użytkownik ponownie włącza Auto-scroll."""
        if self.autoscroll_var.get():
            # Jeśli była włączona lupa lub rączka na toolbarze - wyłączamy ją
            if self.toolbar.mode:
                self.toolbar.mode = ""
                self._refresh_canvas([], []) # Wymuszenie odświeżenia stanu wewnętrznego

    def update_plot(self):
        """Pancerna pętla pomiarowa odporna na przerwy w transmisji i anomalie.
        Czas trwania eksperymentu jest kontrolowany przez niezależny zegar systemowy komputera."""
        
        # --- AGRESYWNE ODRZUCANIE DANYCH HISTORYCZNYCH (FLUSH & PURGE) ---
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Pętla czyta wszystko, co zalega w pamięci podręcznej FIFO i sterownikach OS,
            # dopóki port szeregowy nie zostanie całkowicie opróżniony (in_waiting == 0).
            # Dajemy systemowi 100ms na zebranie i wyrzucenie wszystkich starych pakietów.
            start_flush = time.time()
            while ser.in_waiting > 0 or (time.time() - start_flush < 0.100):
                if ser.in_waiting > 0:
                    ser.read_all()  # Odessanie i bezpowrotne skasowanie bajtów
                time.sleep(0.005)
                
            print("Czyszczenie zakończone sukcesem. Magistrala UART jest całkowicie pusta.")
        except Exception as e:
            print(f"Ostrzeżenie przy czyszczeniu bufora: {e}")

        raw_ts = []
        raw_ds = []
        t0 = None
        
        start_system_time = None  # Niezależny zegar systemowy komputera
        last_draw_time = time.time()
        
        print("Waiting for data...")
        
        while not self.stop_requested:
            time.sleep(0.005)

            # === GWARANCJA AUTOMATYCZNEGO STOPU ===
            # Jeśli pomiar już wystartował (mamy czas t0), sprawdzamy zegar komputera.
            # Zapobiega to zapętleniu, nawet jeśli czujnik na koniec zgubi zasięg i zwraca None.
            if start_system_time is not None:
                elapsed_system_time_ms = (time.time() - start_system_time) * 1000.0
                if elapsed_system_time_ms > self.current_timeout:
                    print(f"Pomiar zakończony bezwarunkowo przez zegar systemowy: {elapsed_system_time_ms:.1f}ms")
                    break

            try:
                point = self._read_serial_line()
                
                # Jeśli funkcja zwróciła None (brak danych lub zły dystans), 
                # przechodzimy do kolejnej iteracji, ale zegar systemowy na górze pętli i tak nas rozliczy!
                if point is None:
                    continue
                
                # Odbieramy 3 wartości, ale zmienną btn_state w trakcie pomiaru ignorujemy.
                t_raw, d, btn_state = point
                
                # Inicjalizacja punktów startowych przy pierwszym poprawnym pakiecedanych
                if t0 is None:
                    t0 = t_raw
                    start_system_time = time.time()  # Rusza niezależny stoper komputera

                # Obliczenie czasu relatywnego na podstawie ramek z Arduino
                t = t_raw - t0

                # FILTR ANOMALII CZASU: 
                # Odrzucamy tylko ewidentne błędy bitowe transmisji (np. ujemny czas lub totalny kosmos),
                # ale pozwalamy czasowi płynąć naturalnie dalej w przedziale pomiarowym.
                if t < 0 or t > self.current_timeout * 2.0:
                    print(f"Odrzucono anomalny czas z Arduino: t={t}ms (surowy t_raw={t_raw}) t0 = {t0}")
                    continue

                raw_ts.append(t)
                raw_ds.append(d)

                # Odświeżanie wykresu (Throttling do 25 Hz)
                now = time.time()
                if now - last_draw_time > 0.040:
                    last_draw_time = now
                    times, distances = aggregate_data(raw_ts, raw_ds)
                    
                    if self.align_zero_var.get() and times:
                        t_start = times[0]
                        d_start = distances[0]
                        aligned_times = [x - t_start for x in times]
                        aligned_distances = [y - d_start for y in distances]
                        self.root.after(0, self._refresh_canvas, aligned_times, aligned_distances)
                    else:
                        self.root.after(0, self._refresh_canvas, times, distances)

                # Dodatkowe zabezpieczenie kończące pętlę na podstawie czasu Arduino
                if t > self.current_timeout:
                    print(f"Pomiar zakończony normalnie przez zegar Arduino: {t}ms")
                    break

            except Exception as e:
                print(f"Błąd wewnątrz pętli while: {e}")
                continue

        # Sekcja rysowania końcowego po wyjściu z pętli while
        try:
            if raw_ts:
                times, distances = aggregate_data(raw_ts, raw_ds)
                if self.align_zero_var.get() and times:
                    t_start = times[0]
                    d_start = distances[0]
                    aligned_times = [x - t_start for x in times]
                    aligned_distances = [y - d_start for y in distances]
                    self.root.after(0, self._refresh_canvas, aligned_times, aligned_distances)
                else:
                    self.root.after(0, self._refresh_canvas, times, distances)
        except Exception:
            pass
        finally:
            self.plotting = False
            self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.cease_btn.config(state=tk.DISABLED))
            self.root.after(0, lambda: self.clear_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.time_entry.config(state=tk.NORMAL))  

    def _read_serial_line(self):
        """Odczytuje port szeregowy i zwraca SUROWE wartości (t_raw, d). 
        Nie filtruje czasu trwania eksperymentu, jedynie poprawność pakietu i fizyczny zasięg."""
        try:
            if ser.in_waiting == 0:
                return None

            data_bytes = ser.readline()
            if not data_bytes:
                return None

            data = data_bytes.decode(errors='ignore').strip()
            if not data or ',' not in data:
                return None

            parts = data.split(',')
            if len(parts) != 3:
                return None
                
            try:
                # parts[0] to zawsze CZAS, parts[1] to zawsze DYSTANS
                t_raw = int(parts[0].strip())
                d = int(parts[1].strip())
                btn_state = int(parts[2].strip()) # czytamy stan guzika, ale go ignorujemy 
            except ValueError:
                print(f"Pominięto uszkodzone dane: {data}")
                return None
            
            # Filtr fizycznego zasięgu czujnika LIDAR (np. 2 cm - 499 cm)
            # dostosuj te wartości do czujnika i długości w doświadczeniu (równi pochyłej)
            MIN_DISTANCE = 2    # cm
            MAX_DISTANCE = 500  # cm 
            # UWAGA: zmiana zakresu zmiennej MAX_DISTANCE jest niewystarczająca; trzeba również
            # zmienić tą wartość w oprogramowaniu płytki arduino (main.cpp)
            if d < MIN_DISTANCE or d > MAX_DISTANCE:
                print(f"Odrzucono anomalny dystans: d={d}cm (Poza zakresem czujnika)")
                return None

            return t_raw, d, btn_state

        except Exception as e:
            print(f"Chwilowy błąd transmisji: {e}")
            return None

    def _refresh_canvas(self, times, distances):
        """Aktualizuje linię wykresu w głównym wątku Tkintera."""
        if not times or self.current_line is None:
            return

        try:
            offset_x = self.line_offsets.get(self.current_line, 0.0)
            offset_y = self.line_offsets_y.get(self.current_line, 0.0) 
            shifted_times = [x + offset_x for x in times]
            shifted_distances = [y + offset_y for y in distances] 
            
            self.current_line.set_data(shifted_times, shifted_distances) 

            # Przemieszczanie kamery zależy teraz wyłącznie od zaznaczonego checkboxa
            if self.autoscroll_var.get():
                min_d, max_d = min(distances), max(distances)
                margin = max(5, (max_d - min_d) * 0.1)
                
                self.ax.set_xlim(times[0], times[-1])
                self.ax.set_ylim(min_d - margin, max_d + margin)

            self.canvas.draw_idle()
            
        except Exception as e:
            print(f"Chwilowy problem z odświeżeniem płótna: {e}")

    def on_line_pick(self, event):
        """1. Wywoływane w momencie kliknięcia lewym przyciskiem myszy w linię."""
        # Ignorujemy próby przesuwania w trakcie trwania aktywnego pomiaru
        if self.plotting:
            return
        
        # Reagujemy TYLKO na lewy przycisk myszy (button == 1) ---
        if event.mouseevent.button != 1:
            return

        # Przywrócenie standardowej grubości poprzednio wybranej linii
        if self.selected_line is not None:
            self.selected_line.set_linewidth(1.5)

        # Przejęcie nowej linii i pogrubienie jej w celach wizualnych
        self.selected_line = event.artist
        self.selected_line.set_linewidth(2.0)
        
        # Zapamiętanie współrzędnej X wykresu, na której stał kursor w chwili kliknięcia
        self.press_x = event.mouseevent.xdata
        self.press_y = event.mouseevent.ydata  
        self.is_dragging = True
        
        self.canvas.draw_idle()
        print(f"Chwycono serię: {self.selected_line.get_label()}")
        
    def on_line_drag(self, event):
        """2. Wywoływane przy każdym ruchu myszy nad obszarem wykresu."""
        if not self.is_dragging or self.selected_line is None or event.xdata is None or self.press_x is None or event.ydata is None or self.press_y is None: 
            return

        dx = event.xdata - self.press_x
        dy = event.ydata - self.press_y 
        if dx == 0 and dy == 0: 
            return

        self.press_x = event.xdata
        self.press_y = event.ydata 

        self.line_offsets[self.selected_line] = self.line_offsets.get(self.selected_line, 0.0) + dx
        self.line_offsets_y[self.selected_line] = self.line_offsets_y.get(self.selected_line, 0.0) + dy 

        x_data, y_data = self.selected_line.get_data()
        new_x = [x + dx for x in x_data]
        new_y = [y + dy for y in y_data] 
        self.selected_line.set_data(new_x, new_y) 

        # --- AKTUALIZACJA WSKAŹNIKA W LEGENDACH NA ŻYWO ---
        lbl_x = self.line_offsets[self.selected_line]
        lbl_y = self.line_offsets_y[self.selected_line]
        
        # Pobieramy podstawowy kolor linii, aby zachować spójność opisu
        color = self.selected_line.get_color()
        self.selected_line.set_label(f"Run {color} [Δt:{lbl_x:+.0f}ms, Δd:{lbl_y:+.1f}cm]")
        self.ax.legend()

        self.canvas.draw_idle()

    def on_bg_click(self, event):
        """Wywoływane przy każdym kliknięciu myszą na płótnie."""
        # Jeśli użytkownik ma włączoną lupę/rączkę z toolbaru, nie resetujemy zaznaczenia
        if self.toolbar.mode:
            return
        
        # Odznaczamy linię TYLKO przy kliknięciu LEWYM przyciskiem myszy w tło ---
        if event.button != 1:
            return

        # Sprawdzamy, czy kliknięcie nie pochodzi z 'pick_event' (czyli czy kliknięto w tło)
        # Matplotlib przy trafnym kliknięciu w linię najpierw wywołuje on_line_pick, a potem to zdarzenie.
        # Jeśli kliknięto w puste tło, is_dragging będzie równe False.
        if not self.is_dragging and self.selected_line is not None:
            self.selected_line.set_linewidth(1.5) # Powrót do cienkiej linii
            self.selected_line = None
            self.canvas.draw_idle()
            print("Odznaczono serię pomiarową.")

    def on_line_release(self, event):
        """3. Wywoływane w momencie puszczenia przycisku myszy."""
        if self.is_dragging:
            self.is_dragging = False
            self.press_x = None
            self.press_y = None # 
            print(f"Upuszczono serię na pozycji offsetu: {self.line_offsets.get(self.selected_line, 0.0):.1f} ms")

    def change_scale(self, event):
        """Obsługa przybliżania i oddalania wykresu rolką myszy."""
        if event.inaxes != self.ax: 
            return  
        
        xdata, ydata = event.xdata, event.ydata
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()

        base_scale = 1.5
        scale_factor = 1 / base_scale if event.button == 'up' else base_scale

        new_width = (cur_xlim[1] - xdata) * scale_factor
        new_left = (xdata - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - ydata) * scale_factor
        new_bottom = (ydata - cur_ylim[0]) * scale_factor

        self.ax.set_xlim([xdata - new_left, xdata + new_width])
        self.ax.set_ylim([ydata - new_bottom, ydata + new_height])
        self.canvas.draw_idle()

    def clear_plot(self):
        """Czyści dane z osi bez usuwania obiektów opisów."""
        # Bezpieczne usunięcie wszystkich narysowanych linii serii
        while self.ax.lines:
            self.ax.lines[0].remove()
            
        self.current_line = None
        self.selected_line = None
        self.press_x = None
        self.press_y = None 
        self.is_dragging = False
        self.line_offsets.clear()
        self.line_offsets_y.clear() 
        
        # Bezpieczne usunięcie legendy, jeśli istnieje
        if self.ax.get_legend():
            self.ax.get_legend().remove()
        
        # Reset osi do widoku początkowego
        self.ax.set_xlim(0, 10)
        self.ax.set_ylim(0, 10)
        self.canvas.draw_idle()
        self.line_colors = iter(['b', 'g', 'r', 'c', 'm', 'y', 'k'])

    def save_plot(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.png',
            filetypes=[('PNG', '*.png'), ('JPEG', '*.jpg'), ('All files', '*.*')]
        )
        if file_path:
            self.fig.savefig(file_path)
            messagebox.showinfo("Save", f"Plot saved to {file_path}")

    def quit_app(self):
        self.stop_requested = True
        try:
            if 'ser' in globals() and ser.is_open:
                ser.close()
        except Exception:
            pass
        self.root.quit()


# === MAIN ===
if __name__ == "__main__":
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    except Exception as e:
        messagebox.showerror("Serial Port Error", f"Error opening serial port: {e}")
        exit(1)

    root = tk.Tk()
    app = DistanceApp(root)
    root.mainloop()
