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
# Exact 8 colors optimized for distinct comparisons
COLORS = ['b', 'g', 'r', 'c', 'm', 'y', 'k']

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
        self.line_colors = iter(COLORS) # iterator kolorków (niebieski, zielony, czerwony itd.). Każdy nowy wykres/pomiar dostanie automatycznie kolejny kolor z listy

        # --- Zmienne kontrolne ---
        self.plotting = False       # czy pomiar aktualnie trwa (zapobiega jednoczesnemu uruchomieniu kilku wątków pomiarowych)
        self.stop_requested = False # czy użytkownik zażądał zatrzymania pomiaru
        self.app_quit_requested = False  # <-- flaga całkowitego zamknięcia aplikacji
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
        # Uruchomienie permanentnego wątku nasłuchu przycisku sprzętowego
        threading.Thread(target=self.hardware_trigger_loop, daemon=True).start()
        
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
        """Inicjalizuje proces zbierania danych pomiarowych z czujnika LIDAR."""
        # Sprawdzenie, czy pętla pomiarowa już działa. Jeśli tak, wyświetla komunikat informacyjny i przerywa działanie funkcji.
        # Chroni to przed przypadkowym wygenerowaniem nieskończonej liczby wątków tła.
        if self.plotting:
            messagebox.showinfo("Measurement", "Measurement already running.")
            return
        
        # Walidacja wprowadzonego czasu trwania pomiaru 
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

        self.start_btn.config(state=tk.DISABLED)    # BLOKADA STARTU (użytkownik nie może kliknąć "Start measurement" ponownie)
        self.cease_btn.config(state=tk.NORMAL)      # AKTYWACJA MOŻLIWOŚCI ZATRZYMANIA (użytkownik może kliknąć "Cease measurement")
        self.clear_btn.config(state=tk.DISABLED)    # BLOKADA CZYSZCZENIA (użytkownik nie może kliknąć "Clear plot")
        self.time_entry.config(state=tk.DISABLED)   # BLOKADA ZMIANY TIMEOUTu (blokada pola tekstowego podczas pomiaru)

        # UTWORZENIE NOWEJ LINII DLA TEGO POMIARU
        try:
            color = next(self.line_colors)
        # gdy wyczerpano kolory z listy, iterator jest automatycznie odnawiany od zera
        except StopIteration: 
            self.line_colors = iter(COLORS)
            color = next(self.line_colors)

        self.current_line, = self.ax.plot([], [], color=color, label=f"Run {color}", picker=5)
        self.line_offsets[self.current_line] = 0.0      # Inicjalizacja przesunięcia w X na 0
        self.line_offsets_y[self.current_line] = 0.0    # Inicjalizacja przesunięcia w Y na 0
        self.ax.legend()

        threading.Thread(target=self.update_plot, daemon=True).start()
        # Uruchamia metodę update_plot w osobnym wątku systemowym. 
        # Flaga daemon=True (wątek demona) oznacza, że zakończenie działania aplikacji głównej (zamknięcie okna) automatycznie i natychmiastowo ubije ten wątek roboczy, eliminując ryzyko wiszenia procesu w pamięci RAM komputera.

    def cease_measurement(self):
        """Odpowiada za asynchroniczne, programowe przerwanie pętli pomiarowej. Nie zatrzymuje wątku w sposób agresywny. 
        Zamiast tego wątek roboczy update_plot przy najbliższej iteracji wyjdzie z pętli"""
        self.stop_requested = True
        self.cease_btn.config(state=tk.DISABLED) # uniemożliwia ponowne kliknięcie "Cease measurement"

    def update_plot(self):
        """Pancerna pętla pomiarowa odporna na przerwy w transmisji i anomalie.
        Czas trwania eksperymentu jest kontrolowany przez niezależny zegar systemowy komputera.
        Zoptymalizowana pod kątem buforowania i lagów systemu Windows bez straty danych pomiarowych."""
        
        # AGRESYWNE ODRZUCANIE DANYCH HISTORYCZNYCH (FLUSH & PURGE)
        try:
            # W tej komunikacji istnieją dwa niezależne bufory sprzętowe/systemowe:
            # Bufor odbiornika (w komputerze/Pythonie)
            # Bufor nadajnika (w Arduino)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            # Czyszczenie bufora po stronie Pythona (reset_input_buffer()) może okazać się niewystarczające
            # Gdy wywołasz ser.reset_input_buffer(), komputer błyskawicznie opróżnia twój lokalny bufor. Jednak Arduino w tej samej milisekundzie nadal przesyła kolejne bajty przez kabel USB.
            
            # Pętla czyta wszystko, co zalega w pamięci podręcznej FIFO i sterownikach OS,
            # dopóki port szeregowy nie zostanie całkowicie opróżniony (in_waiting == 0).
            # Dajemy systemowi 100ms na zebranie i wyrzucenie wszystkich starych pakietów.
            # TODO: można zamiast agresywnego czyszczenia zaimplementować komunikację typu Zapytanie-Odpowiedź
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
            # Minimalny odpoczynek wątku, aby nie przeciążać procesora
            time.sleep(0.001)

            # === GWARANCJA AUTOMATYCZNEGO STOPU (po dt > timeout) ===
            # Jeśli pomiar już wystartował (mamy czas t0), sprawdzamy zegar komputera.
            # Zapobiega to zapętleniu, nawet jeśli czujnik na koniec zgubi zasięg i zwraca None.
            if start_system_time is not None:
                elapsed_system_time_ms = (time.time() - start_system_time) * 1000.0
                if elapsed_system_time_ms > self.current_timeout:
                    print(f"Pomiar zakończony bezwarunkowo przez zegar systemowy: {elapsed_system_time_ms:.1f}ms")
                    break

            try:
                # Jeśli w buforze Windowsa nie ma danych, przechodzimy do kolejnego obiegu i czekamy
                if ser.in_waiting == 0:
                    continue

                # POTOK KONSUMPCJI: Błyskawicznie wymiata wszystkie punkty nagromadzone w buforze Windowsa.
                # Dzięki temu przetwarzamy dane w czasie rzeczywistym bez straty ani jednego punktu pomiarowego.
                while ser.in_waiting > 0 and not self.stop_requested:
                    point = self._read_serial_line()

                    # Jeśli funkcja zwróciła None, ignorujemy paczkę, ale mikropętla działa dalej
                    if point is None:
                        continue
                
                    # Odbieramy 3 wartości, ale zmienną btn_state w trakcie pomiaru ignorujemy.
                    # Dzięki temu pętla nie zrywa serii pomiarowej, a kod się nie wyłoży na liczbie kolumn.
                    t_raw, d, btn_state = point 
                
                    # Inicjalizacja punktów startowych przy pierwszym poprawnym pakiecie danych
                    if t0 is None:
                        t0 = t_raw
                        start_system_time = time.time()  # Rusza niezależny stoper komputera

                    # Obliczenie czasu relatywnego na podstawie ramek z Arduino
                    t = t_raw - t0

                    # FILTR ANOMALII CZASU: 
                    # Odrzucamy tylko ewidentne błędy bitowe transmisji (np. ujemny czas lub czas znacząco wykraczający poza oczekiwany zakres),
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
                    
                        # opcjonalne zerowanie wykresu (początek osi na zerze) tuż przed jego wyświetleniem na ekranie. 
                        # Decyduje o tym, czy wykres ma pokazywać wartości surowe, czy wartości liczone od zera.
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
                # opcjonalne zerowanie wykresu
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
        """Odczytuje port szeregowy i zwraca SUROWE wartości (t_raw, d) oraz stan przycisku -> (czas, dystans, stan_przycisku). 
        Nie filtruje czasu trwania eksperymentu, jedynie poprawność pakietu i fizyczny zasięg."""
        try:
            # Sprawdza, czy w buforze sprzętowym systemu operacyjnego znajdują się jakiekolwiek nieprzeczytane bajty. 
            # Zapobiega to blokowaniu wątku na operacji odczytu.
            if ser.in_waiting == 0:
                return None

            # pobiera strumień aż do napotkania znaku końca linii \n
            data_bytes = ser.readline()
            if not data_bytes:
                return None

            # transformuje bajty do formatu tekstowego UTF-8, ignorując uszkodzone znaki powstałe w wyniku zakłóceń elektromagnetycznych (EMI), 
            # oraz obcina znaki niedrukowalne (\r, \n).
            data = data_bytes.decode(errors='ignore').strip()
            if not data or ',' not in data:
                return None

            parts = data.split(',')
            if len(parts) != 3: # oczekujemy 3 elementów (czas, dystans, stan_przycisku)
                return None
                
            try:
                # parts[0] to zawsze CZAS, parts[1] to zawsze DYSTANS, parts[2] to zawsze STAN PRZYCISKU
                t_raw = int(parts[0].strip())
                d = int(parts[1].strip())
                btn_state = int(parts[2].strip()) # 1 = puszczony, 0 = wciśnięty
            except ValueError:
                print(f"Pominięto uszkodzone dane: {data}")
                return None
            
            # Filtr fizycznego zasięgu czujnika LIDAR (np. 2 cm - 500 cm)
            # TODO: dostosuj te wartości do czujnika i długości w doświadczeniu (równi pochyłej)
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
        # Jeśli jest brak nowych danych lub linia wykresu nie została jeszcze utworzona, funkcja natychmiast przerywa działanie.
        if not times or self.current_line is None:
            return

        try:
            # geometrycznym przesuwaniem wykresu w locie
            # sprawdzenie czy użytkownik przesunął wcześniej linię myszką w poziomie lub w pionie. 
            # Jeśli tak, to do każdej nowej współrzędnej czasu X oraz odległości Y pobranej z Arduino automatycznie dodawana jest wartość tego przesunięcia. 
            offset_x = self.line_offsets.get(self.current_line, 0.0)
            offset_y = self.line_offsets_y.get(self.current_line, 0.0) 
            shifted_times = [x + offset_x for x in times]
            shifted_distances = [y + offset_y for y in distances] 
            
            self.current_line.set_data(shifted_times, shifted_distances) 

            # Przemieszczanie kamery zależy od zaznaczonego checkboxa
            # Sprawdza najmniejszą oraz największą odległość zarejestrowaną w obecnej serii i oblicza bezpieczny margines pionowy (minimum 5 centymetrów lub 10% całego zakresu ruchu). 
            if self.autoscroll_var.get():
                min_d, max_d = min(distances), max(distances)
                margin = max(5, (max_d - min_d) * 0.1)

                # Automatycznie docina granice osi pionowej (odległość) oraz poziomej (czas od pierwszego do ostatniego punktu).    
                # Powoduje to, że wykres samoczynnie przesuwa się w prawo i dopasowuje do wysokości ruchu, dzięki czemu czoło rysowanej linii jest zawsze idealnie widoczne na ekranie. 
                self.ax.set_xlim(times[0], times[-1])
                self.ax.set_ylim(min_d - margin, max_d + margin)

            self.canvas.draw_idle()
            
        except Exception as e:
            print(f"Chwilowy problem z odświeżeniem płótna: {e}")

    def toggle_autoscroll(self):
        """Resetuje tryb nawigacji toolbara, jeśli użytkownik ponownie włącza Auto-scroll."""
        # Pasek narzędzi pod wykresem (toolbar) ma własną logikę działania. Kiedy klikasz na lupę lub rączkę, Matplotlib wchodzi w wewnętrzny tryb interakcji i "zamraża" osie, aby użytkownik mógł swobodnie badać wykres.
        # Jeśli w tym samym czasie zaznaczysz opcję Auto-scroll, funkcja odświeżająca wykres (_refresh_canvas) spróbuje siłą przesunąć kamerę za jadącym wózkiem. 
        # W efekcie program dostawał sprzeczne instrukcje (toolbar chciał trzymać widok lupy, a Auto-scroll chciał go przesunąć), co powodowało, że automatyczne śledzenie całkowicie się blokowało i przestawało działać nawet po odznaczeniu lupy.
        if self.autoscroll_var.get():
            # Jeśli była włączona lupa lub rączka na toolbarze - wyłączamy ją
            if self.toolbar.mode:
                self.toolbar.mode = ""
                self._refresh_canvas([], []) # Wymuszenie odświeżenia stanu wewnętrznego

    def hardware_trigger_loop(self):
        """Permanentny wątek nasłuchujący przycisku sprzętowego Arduino. 
        Uruchamia nowy pomiar wyłącznie, gdy aplikacja jest w stanie spoczynku."""
        last_btn_state = 1  # 1 oznacza domyślnie puszczony przycisk (INPUT_PULLUP)
        
        while not self.app_quit_requested: # Pętla reaguje tylko na wyjście z programu
            time.sleep(0.010) # 10ms odpoczynku w zupełności wystarczy (częstotliwość 100Hz)
            
            # Jeśli trwa aktywny pomiar, ten wątek "śpi" i nie marnuje zasobów procesora,
            # ponieważ to główna pętla update_plot zarządza teraz odczytem z portu.
            if self.plotting:
                continue
                
            # Sekcja nasłuchu uruchamia się TYLKO poza aktywnym pomiarem
            point = self._read_serial_line()
            if point is not None:
                _, _, btn_state = point
                
                # Wykrywanie ZBOCZA NARASTAJĄCEGO (Przejście z 0 na 1 -> puszczenie przycisku)
                if last_btn_state == 0 and btn_state == 1:
                    print("Wykryto zwolnienie blokady! Uruchamianie pomiaru z poziomu Arduino...")
                    # Bezpieczne wywołanie start_measurement w głównym wątku GUI Tkintera
                    self.root.after(0, self.start_measurement)
                
                # Aktualizacja stanu przycisku do kolejnej iteracji
                last_btn_state = btn_state

    def on_line_pick(self, event):
        """Wywoływane w momencie kliknięcia lewym przyciskiem myszy w linię.
        Odpowiada za poprawną inicjalizację trybu przesuwania."""
        # Ignorujemy próby przesuwania w trakcie trwania aktywnego pomiaru
        if self.plotting:
            return
        
        # Reagujemy TYLKO na lewy przycisk myszy (button == 1) 
        if event.mouseevent.button != 1:
            return

        # Przywrócenie standardowej grubości poprzednio wybranej linii
        if self.selected_line is not None:
            self.selected_line.set_linewidth(1.5)

        # Przejęcie nowej linii i pogrubienie jej w celach wizualnych (sygnał na ekranie, która seria pomiarowa została wybrana do edycji)
        self.selected_line = event.artist
        self.selected_line.set_linewidth(2.0)
        
        # Zapamiętanie współrzędnych X i Y wykresu, na których stał kursor w chwili kliknięcia
        self.press_x = event.mouseevent.xdata
        self.press_y = event.mouseevent.ydata  
        self.is_dragging = True
        
        self.canvas.draw_idle()
        print(f"Chwycono serię: {self.selected_line.get_label()}")
        
    def on_line_drag(self, event):
        """Wywoływane przy każdym ruchu myszy nad obszarem wykresu."""
        if not self.is_dragging or self.selected_line is None or event.xdata is None or self.press_x is None or event.ydata is None or self.press_y is None: 
            return

        dx = event.xdata - self.press_x
        dy = event.ydata - self.press_y 
        if dx == 0 and dy == 0: 
            return

        # Nadpisujemy stary punkt kliknięcia aktualną pozycją myszy. Dzięki temu przy kolejnym minimalnym ruchu myszy (za ułamek sekundy), 
        # dx i dy będą liczone od obecnego miejsca, a nie od miejsca, gdzie kliknięto na samym początku. To zapewnia płynność ruchu.
        self.press_x = event.xdata
        self.press_y = event.ydata 

        self.line_offsets[self.selected_line] = self.line_offsets.get(self.selected_line, 0.0) + dx
        self.line_offsets_y[self.selected_line] = self.line_offsets_y.get(self.selected_line, 0.0) + dy 

        # Pobieramy z Matplotlib aktualne tablice współrzędnych (wszystkie punkty X i Y), z których narysowana jest wybrana linia.
        # Przechodzimy przez każdy punkt na linii i dodajemy do niego nasze przesunięcie (dx i dy).
        x_data, y_data = self.selected_line.get_data()
        new_x = [x + dx for x in x_data]
        new_y = [y + dy for y in y_data] 
        self.selected_line.set_data(new_x, new_y) 

        # AKTUALIZACJA WSKAŹNIKA W LEGENDACH NA ŻYWO 
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
        
        # Odznaczamy linię TYLKO przy kliknięciu LEWYM przyciskiem myszy w tło
        if event.button != 1:
            return

        # Sprawdzamy, czy kliknięcie nie pochodzi z 'pick_event' (czyli czy kliknięto w tło)
        # Matplotlib przy trafnym kliknięciu w linię najpierw wywołuje on_line_pick, a potem to zdarzenie.
        # Jeśli kliknięto w puste tło, is_dragging będzie równe False (odpowiada za to funkcja on_line_release).
        if not self.is_dragging and self.selected_line is not None:
            self.selected_line.set_linewidth(1.5) # Powrót do cienkiej linii
            self.selected_line = None
            self.canvas.draw_idle()
            print("Odznaczono serię pomiarową.")

    def on_line_release(self, event):
        """Wywoływane w momencie puszczenia przycisku myszy."""
        if self.is_dragging:
            self.is_dragging = False
            self.press_x = None
            self.press_y = None 
            print(f"Upuszczono serię na pozycji offsetu: {self.line_offsets.get(self.selected_line, 0.0):.1f} ms, {self.line_offsets_y.get(self.selected_line, 0.0):.1f} cm")

    def change_scale(self, event):
        """Obsługa przybliżania i oddalania wykresu rolką myszy."""
        # Sprawdzamy, czy kursor myszy znajduje się bezpośrednio nad obszarem osi wykresu
        if event.inaxes != self.ax: 
            return  
        
        # zapisujemy współrzędne na wykresie, w których stoi kursor w momencie obrotu rolki
        xdata, ydata = event.xdata, event.ydata
        # pobieramy aktualne limity (zakresy) osi X i Y, krotki zawierające wartości [lewa, prawa] oraz [dolna, górna]
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()

        base_scale = 1.5    # bazowy współczynnik zmiany widoku
        # Matplotlib przekazuje ruch rolki w górę jako 'up' (przybliżanie), a w dół jako 'down' (oddalanie).
        scale_factor = 1 / base_scale if event.button == 'up' else base_scale

        # Kod dzieli aktualny widok na cztery odcinki, mierzone od pozycji kursora do krawędzi wykresu, a następnie mnoży je przez scale_factor:
        # new_width: Nowa odległość od kursora do prawej krawędzi osi X.
        # new_left: Nowa odległość od kursora do lewej krawędzi osi X.
        # new_height: Nowa odległość od kursora do górnej krawędzi osi Y.
        # new_bottom: Nowa odległość od kursora do dolnej krawędzi osi Y.
        # Dzięki przemnożeniu wszystkich czterech stron osobnym wektorem relatywnie do pozycji myszy, punkt pod kursorem pozostanie nienaruszony (nie ucieknie z ekranu).
        new_width = (cur_xlim[1] - xdata) * scale_factor
        new_left = (xdata - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - ydata) * scale_factor
        new_bottom = (ydata - cur_ylim[0]) * scale_factor

        # Ustala nowe oficjalne granice wykresu. Lewa krawędź to pozycja kursora minus nowa odległość lewa, 
        # prawa to pozycja kursora plus nowa odległość prawa (analogicznie dla osi Y).
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
        self.line_colors = iter(COLORS)

    def save_plot(self):
        """Dodaje obsługę dedykowanego przycisku Save Plot bezpośrednio w panelu sterowania aplikacji. 
        Ta funkcja pod względem czysto technicznym dubluje możliwość zapisu, ponieważ fabryczny pasek narzędzi Matplotlib (toolbar) posiada już własną ikonkę dyskietki, która realizuje dokładnie to samo zadanie."""
        file_path = filedialog.asksaveasfilename(
            defaultextension='.png',
            filetypes=[('PNG', '*.png'), ('JPEG', '*.jpg'), ('All files', '*.*')]
        )
        if file_path:
            self.fig.savefig(file_path)
            messagebox.showinfo("Save", f"Plot saved to {file_path}")

    def quit_app(self):
        """Odpowiada za bezpieczne zamknięcie aplikacji oraz prawidłowe nawiązanie i zakończenie połączenia szeregowego (RS-232 / UART)"""
        # Zamykamy wątki działające w tle.
        self.stop_requested = True
        self.app_quit_requested = True
        # Zamykamy połączenie i zwalniamy port w systemie operacyjnym. Jeśli program zapomniałby zamknąć portu, system mógłby go zablokować
        # i ponowne uruchomienie aplikacji zgłosiłoby błąd dostępu.
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
