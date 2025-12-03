import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from smartcard.System import readers
from smartcard.util import toHexString

#KLASA DEKODUJĄCA SMS (PDU)
class PDUDecoder:
    @staticmethod
    def swap_nibbles(hex_str):
        """Zamienia cyfry miejscami (np. '19' -> '91' dla numerów tel)"""
        res = ""
        for i in range(0, len(hex_str), 2):
            if i+1 < len(hex_str):
                res += hex_str[i+1] + hex_str[i]
            else:
                res += hex_str[i] + 'F'
        return res.replace('F', '')

    @staticmethod
    def decode_7bit(pdu_hex):
        """Rozpakowuje skompresowany tekst GSM 7-bit"""
        bytes_list = [int(pdu_hex[i:i+2], 16) for i in range(0, len(pdu_hex), 2)]
        
        decoded = ""
        current = 0
        shift = 0
        
        for byte_val in bytes_list:
            current |= (byte_val << shift)
            char_code = current & 0x7F
            current >>= 7
            shift += 1
            
            if char_code < 128: decoded += chr(char_code)
            else: decoded += "?"
            
            if shift == 7:
                decoded += chr(current & 0x7F)
                current = 0
                shift = 0
                
        return decoded

    @staticmethod
    def parse_sms(raw_bytes):
        """Główna funkcja analizująca ramkę PDU"""
        try:
            pdu = "".join([f"{b:02X}" for b in raw_bytes])
            idx = 0
            
            # 1. Długość numeru SMSC
            smsc_len_bytes = int(pdu[idx:idx+2], 16)
            idx += 2
            idx += (smsc_len_bytes * 2) # Przeskocz SMSC
            
            # 2. Flagi
            first_octet = int(pdu[idx:idx+2], 16)
            idx += 2
            
            # 3. Nadawca
            sender_len_digits = int(pdu[idx:idx+2], 16)
            idx += 2
            sender_type = int(pdu[idx:idx+2], 16)
            idx += 2
            sender_bytes = (sender_len_digits + 1) // 2
            sender_raw = pdu[idx : idx + sender_bytes*2]
            
            # Obsługa numeru tekstowego (Alphanumeric, np. "PLAY") vs Telefonu
            if sender_type == 0xD0: 
                # Typ Alfanumeryczny 7-bit
                sender = PDUDecoder.decode_7bit(sender_raw)
                # Obcinamy śmieci z nazwy nadawcy (długość to liczba znaków * 4/7, uproszczone)
                limit_sender = (sender_len_digits * 4) // 7
                sender = sender[:limit_sender]
            else:
                # Zwykły numer telefonu
                sender = PDUDecoder.swap_nibbles(sender_raw)
                
            idx += (sender_bytes * 2)
            
            # 4. PID i DCS
            pid = pdu[idx:idx+2]
            dcs = int(pdu[idx+2:idx+4], 16)
            idx += 4
            
            # 5. Data
            ts_raw = pdu[idx:idx+14]
            ts = PDUDecoder.swap_nibbles(ts_raw)
            date_str = f"20{ts[0:2]}-{ts[2:4]}-{ts[4:6]} {ts[6:8]}:{ts[8:10]}"
            idx += 14
            
            # 6. Długość wiadomości (UDL) - TO JEST KLUCZ DO NAPRAWY
            msg_len = int(pdu[idx:idx+2], 16) # W trybie 7-bit to liczba ZNAKÓW
            idx += 2
            
            # 7. Treść
            ud_hex = pdu[idx:]
            
            if dcs == 0x00:
                full_decoded = PDUDecoder.decode_7bit(ud_hex)
                # --- POPRAWKA: PRZYCINAMY DO DŁUGOŚCI UDL ---
                message = full_decoded[:msg_len] 
            else:
                message = f"(Inne kodowanie: DCS={dcs:02X})"
                
            return sender, date_str, message
            
        except Exception as e:
            return "Nieznany", "Błąd", f"Błąd dekodowania: {e}"


# GŁÓWNA APLIKACJA
class SimReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python SIM Reader - FULL VERSION")
        self.root.geometry("900x700")

        # UI
        frame_top = tk.Frame(root)
        frame_top.pack(pady=10, fill="x", padx=10)
        tk.Label(frame_top, text="Wybierz czytnik:").pack(side="left")
        self.combo_readers = ttk.Combobox(frame_top, state="readonly", width=40)
        self.combo_readers.pack(side="left", padx=10)
        
        frame_btns = tk.Frame(root)
        frame_btns.pack(pady=5)
        
        self.btn_contacts = tk.Button(frame_btns, text="ODCZYTAJ WSZYSTKIE KONTAKTY", command=self.read_contacts, bg="#aaffaa", width=30)
        self.btn_contacts.pack(side="left", padx=10)

        self.btn_sms = tk.Button(frame_btns, text="ODCZYTAJ I ODKODUJ SMS", command=self.read_sms, bg="#aaaaff", width=30)
        self.btn_sms.pack(side="left", padx=10)

        self.log_area = scrolledtext.ScrolledText(root, width=100, height=35, state='disabled', font=("Consolas", 10))
        self.log_area.pack(pady=5, padx=10, fill="both", expand=True)

        self.load_readers()

    def log(self, message):
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')
        self.root.update()

    def clear_log(self):
        self.log_area.config(state='normal')
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state='disabled')

    def load_readers(self):
        try:
            r_list = readers()
            if r_list:
                self.combo_readers['values'] = r_list
                self.combo_readers.current(0)
            else:
                self.combo_readers['values'] = ["Brak czytników"]
                self.combo_readers.current(0)
        except: pass

    def get_conn(self):
        sel = self.combo_readers.get()
        if not sel or "Brak" in sel: return None
        try:
            r = readers()[self.combo_readers.current()]
            c = r.createConnection()
            c.connect()
            return c
        except Exception as e:
            self.log(f"Błąd: {e}")
            return None

    def send_apdu(self, conn, apdu):
        try:
            data, sw1, sw2 = conn.transmit(apdu)
            if sw1 == 0x9F or sw1 == 0x61:
                data, sw1, sw2 = conn.transmit([0xA0, 0xC0, 0x00, 0x00, sw2])
            return data, sw1, sw2
        except: return [], 0, 0

    def parse_contact(self, data):
        # Nazwa do 0xFF
        text = ""
        for b in data[:-14]:
            if b == 0xFF: break
            if 32 <= b <= 126: text += chr(b)
            else: text += "."
        
        # Numer z ostatnich 14 bajtów
        footer = data[-14:]
        bcd_len = footer[0]
        num = ""
        if bcd_len <= 11 and bcd_len != 0xFF:
            for i in range(2, 2+bcd_len):
                if i >= 14: break
                b = footer[i]
                lo, hi = b & 0x0F, (b >> 4) & 0x0F
                if lo <= 9: num += str(lo)
                if hi <= 9: num += str(hi)
        return text, num

    # --- KONTAKTY (Pełna pętla) ---
    def read_contacts(self):
        self.clear_log()
        c = self.get_conn()
        if not c: return

        try:
            self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00])
            self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x7F, 0x10])
            head, sw1, sw2 = self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x6F, 0x3A])
            
            # Twoja karta: długość w ostatnim bajcie nagłówka (jeśli pasuje matematycznie)
            size = (head[2] << 8) + head[3]
            length = head[-1] if (size % head[-1] == 0) else 28
            
            self.log(f">>> Odczyt Kontaktów (Rekord: {length} bajtów)")
            self.log("-" * 60)

            i = 1
            count = 0
            while True:
                data, sw1, sw2 = self.send_apdu(c, [0xA0, 0xB2, i, 0x04, length])
                
                if sw1 == 0x90:
                    if data[0] != 0xFF:
                        name, num = self.parse_contact(data)
                        self.log(f"[{i:03d}] {name:<25} | Tel: {num}")
                        count += 1
                elif sw1 == 0x62 or sw1 == 0x6B or sw1 == 0x6A:
                    # 62 82 = EOF, 6B 00 = Wrong Param (koniec zakresu)
                    break
                else:
                    self.log(f"[{i:03d}] Błąd: {sw1:02X} {sw2:02X}")
                    break
                i += 1
            
            self.log("-" * 60)
            self.log(f"Znaleziono {count} kontaktów. Przeskanowano {i-1} pozycji.")

        except Exception as e:
            self.log(f"Błąd: {e}")

    # --- SMS (Z Dekoderem) ---
    def read_sms(self):
        self.clear_log()
        c = self.get_conn()
        if not c: return

        try:
            self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]) # MF
            self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x7F, 0x10]) # TELECOM
            
            # Pobierz nagłówek pliku SMS
            head, sw1, sw2 = self.send_apdu(c, [0xA0, 0xA4, 0x00, 0x00, 0x02, 0x6F, 0x3C])
            
            rec_len = 176 # Standardowa długość SMS
            
            # --- DYNAMIKA: Obliczamy ile jest miejsc na SMSy ---
            # Jeśli się nie uda obliczyć, przyjmujemy bezpieczne 50
            total_slots = 50 
            if len(head) >= 4:
                file_size = (head[2] << 8) + head[3]
                total_slots = file_size // rec_len
                self.log(f">>> Rozmiar pliku SMS: {file_size} bajtów (Miejsc: {total_slots})")
            
            self.log(f">>> Skanowanie {total_slots} slotów... (Puste będą pomijane)")
            self.log("-" * 80)

            found_count = 0

            for i in range(1, total_slots + 1):
                # Odczyt rekordu
                data, sw1, sw2 = self.send_apdu(c, [0xA0, 0xB2, i, 0x04, rec_len])
                
                # Żeby interfejs się nie zawiesił przy dużej liczbie pustych slotów:
                if i % 5 == 0: self.root.update()

                if sw1 == 0x90:
                    status = data[0]
                    
                    # --- FILTRACJA ---
                    if status == 0x00:
                        # To jest PUSTY slot. 
                        # 'continue' sprawia, że przeskakujemy do następnego numeru pętli
                        # bez wypisywania niczego na ekran.
                        continue
                    
                    elif status in [0x01, 0x03, 0x05, 0x07]:
                        found_count += 1
                        stat_txt = "NOWY" if status == 0x03 else "Stary"
                        
                        # Dekodowanie
                        try:
                            # Przekazujemy dane bez bajtu statusu ([1:])
                            sender, date, msg = PDUDecoder.parse_sms(data[1:])
                            
                            self.log(f"[{i:02d}] {stat_txt} | Od: {sender} | {date}")
                            self.log(f"     Treść: {msg}")
                            self.log("-" * 40)
                        except:
                            self.log(f"[{i:02d}] Błąd dekodowania wiadomości")
                
                # Obsługa końca pliku (gdyby obliczenia rozmiaru były błędne)
                elif sw1 == 0x62 or sw1 == 0x6B or sw1 == 0x6A:
                    break
            
            if found_count == 0:
                self.log("Nie znaleziono żadnych wiadomości SMS na tej karcie.")
            else:
                self.log(f"Zakończono. Znaleziono {found_count} wiadomości.")

        except Exception as e:
            self.log(f"Błąd: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SimReaderApp(root)
    root.mainloop()