import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from smartcard.System import readers
from smartcard.util import toHexString

class SimReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python SIM Reader (PC/SC)")
        self.root.geometry("600x500")

        # 1. Wybór czytnika
        tk.Label(root, text="Wybierz czytnik:").pack(pady=5, padx=10, anchor="w")
        self.combo_readers = ttk.Combobox(root, state="readonly", width=50)
        self.combo_readers.pack(pady=5, padx=10)

        # 2. Przycisk Odczytu
        self.btn_read = tk.Button(root, text="Odczytaj Książkę Telefoniczną", command=self.read_contacts, bg="#dddddd")
        self.btn_read.pack(pady=10)

        # 3. Logi (Okno tekstowe)
        tk.Label(root, text="Logi komunikacji:").pack(padx=10, anchor="w")
        self.log_area = scrolledtext.ScrolledText(root, width=70, height=20, state='disabled')
        self.log_area.pack(pady=5, padx=10)

        # Na starcie ładujemy czytniki
        self.load_readers()

    def log(self, message):
        """Pomocnicza funkcja do wypisywania tekstu w oknie"""
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')
        # Wymuś odświeżenie okna, żeby logi pojawiały się na bieżąco
        self.root.update()

    def load_readers(self):
        """Ładuje listę dostępnych czytników"""
        try:
            r_list = readers()
            if not r_list:
                self.combo_readers['values'] = ["Brak czytników"]
                self.combo_readers.current(0)
                self.log("Nie wykryto czytników. Podłącz urządzenie.")
            else:
                self.combo_readers['values'] = r_list
                self.combo_readers.current(0)
                self.log(f"Znaleziono {len(r_list)} czytnik(ów).")
        except Exception as e:
            self.log(f"Błąd usługi PC/SC: {e}")
            self.log("Upewnij się, że usługa 'Karta inteligentna' działa w Windows.")

    def send_apdu(self, connection, apdu, name="CMD"):
        """Wysyła komendę APDU i zwraca dane, sw1, sw2"""
        try:
            data, sw1, sw2 = connection.transmit(apdu)
            # Odkomentuj poniższą linię, jeśli chcesz widzieć każdą komendę w logach
            # self.log(f"{name}: SW={sw1:02X} {sw2:02X}")
            return data, sw1, sw2
        except Exception as e:
            self.log(f"Błąd transmisji APDU: {e}")
            return [], 0, 0

    def find_real_length(self, connection):
        """Szuka poprawnej długości rekordu metodą prób i błędów"""
        candidates = [28, 32, 30, 34, 26, 22, 14]
        self.log("Szukanie właściwej długości rekordu...")

        for length in candidates:
            # Próba odczytu 1. rekordu z daną długością
            # APDU: CLA=A0, INS=B2, P1=01, P2=04, Le=length
            apdu = [0xA0, 0xB2, 0x01, 0x04, length]
            data, sw1, sw2 = self.send_apdu(connection, apdu, f"Probe {length}")

            if sw1 == 0x90:
                return length
            elif sw1 == 0x6C: # Karta podpowiada długość
                return sw2
        
        return -1

    def parse_text(self, data):
        """Wyciąga czytelny tekst z bajtów (filtruje śmieci)"""
        # Nazwa to zazwyczaj wszystko oprócz ostatnich 14 bajtów
        limit = len(data) - 14
        if limit <= 0: return ""
        
        text = ""
        for i in range(limit):
            byte = data[i]
            if byte == 0xFF: break # Koniec danych
            if 32 <= byte <= 126: # Znaki ASCII
                text += chr(byte)
            else:
                text += "."
        return text

    def read_contacts(self):
        selected = self.combo_readers.get()
        if not selected or "Brak" in selected:
            messagebox.showwarning("Błąd", "Wybierz poprawny czytnik!")
            return

        self.log_area.config(state='normal')
        self.log_area.delete(1.0, tk.END) # Czyść logi
        self.log_area.config(state='disabled')
        
        self.log(f"Łączenie z: {selected}...")

        try:
            # Tworzymy połączenie
            reader_obj = readers()[self.combo_readers.current()]
            connection = reader_obj.createConnection()
            connection.connect()
            
            self.log("Połączono z kartą!")

            # 1. SELECT MF (3F00)
            self.send_apdu(connection, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00], "Select MF")
            
            # 2. SELECT TELECOM (7F10)
            self.send_apdu(connection, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x7F, 0x10], "Select TELECOM")
            
            # 3. SELECT ADN (6F3A) - Książka telefoniczna
            self.send_apdu(connection, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x6F, 0x3A], "Select ADN")

            # 4. Ustalanie długości rekordu
            length = self.find_real_length(connection)
            if length == -1:
                self.log("Nie udało się ustalić długości rekordu. Karta może być zablokowana lub pusta.")
                return
            
            self.log(f"Ustalona długość rekordu: {length} bajtów")
            self.log("-" * 40)

            # 5. Odczyt pętli
            for i in range(1, 11): # Czytamy pierwsze 10
                apdu = [0xA0, 0xB2, i, 0x04, length]
                data, sw1, sw2 = self.send_apdu(connection, apdu, f"Read {i}")
                
                status = f"{sw1:02X} {sw2:02X}"
                hex_data = toHexString(data)
                
                if sw1 == 0x90:
                    text_content = self.parse_text(data)
                    if not text_content: text_content = "<PUSTY>"
                    
                    self.log(f"[{i}] SW: {status} | {hex_data}")
                    self.log(f"    Tekst: {text_content}")
                else:
                    self.log(f"[{i}] SW: {status} | Błąd lub koniec pliku")
                    if sw1 == 0x62: break # Koniec pliku

            self.log("Koniec odczytu.")

        except Exception as e:
            self.log(f"Błąd krytyczny: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SimReaderApp(root)
    root.mainloop()