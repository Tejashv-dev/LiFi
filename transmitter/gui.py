import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import time

BG_MAIN = "#0e1117"
BG_CARD = "#161b22"
BG_INPUT = "#0d1117"
BORDER = "#30363d"
TEXT_MAIN = "#e6edf3"
TEXT_MUTED = "#8b949e"
ACCENT_RED = "#ff3b3b"
ACCENT_CYAN = "#58a6ff"
ACCENT_GREEN = "#3fb950"


class LaserTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OPTICAL TX — Laser Transmitter Console")
        self.root.geometry("540x560")
        self.root.configure(bg=BG_MAIN)

        self.ser = None
        self.is_connected = False
        self.running = True
        self.align_mode = False
        self.bit_speed = tk.IntVar(value=45)

        self._setup_styles()
        self._build_ui()
        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_CARD,
                        foreground=TEXT_MAIN, arrowcolor=TEXT_MAIN, bordercolor=BORDER)
        style.configure("Horizontal.TScale", background=BG_CARD, troughcolor=BG_INPUT)

    def _build_ui(self):
        # Top Bar
        top_bar = tk.Frame(self.root, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        top_bar.pack(fill=tk.X, padx=14, pady=(14, 8))

        tk.Label(top_bar, text="● LASER TX", fg=ACCENT_RED, bg=BG_CARD,
                 font=("Consolas", 11, "bold")).pack(side=tk.LEFT, padx=12, pady=10)

        self.status_lbl = tk.Label(top_bar, text="OFFLINE", fg=TEXT_MUTED, bg=BG_CARD,
                                   font=("Consolas", 9, "bold"))
        self.status_lbl.pack(side=tk.LEFT)

        self.connect_btn = tk.Button(top_bar, text="Connect", bg=ACCENT_CYAN, fg="#000000",
                                     font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12,
                                     cursor="hand2", command=self.toggle_connection)
        self.connect_btn.pack(side=tk.RIGHT, padx=(4, 12), pady=8)

        tk.Button(top_bar, text="↻", bg=BG_INPUT, fg=TEXT_MAIN, font=("Segoe UI", 10, "bold"),
                  relief=tk.FLAT, padx=8, cursor="hand2", command=self.refresh_ports).pack(side=tk.RIGHT, padx=2, pady=8)

        self.port_combo = ttk.Combobox(top_bar, width=16, state="readonly", font=("Consolas", 9))
        self.port_combo.pack(side=tk.RIGHT, padx=4, pady=8)

        # Main Card
        card = tk.Frame(self.root, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 14))

        # Aiming Laser Toggle
        aim_frame = tk.Frame(card, bg=BG_CARD)
        aim_frame.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(aim_frame, text="Alignment Helper:", fg=TEXT_MUTED, bg=BG_CARD,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.aim_btn = tk.Button(aim_frame, text="◎ Turn On Steady Aiming Beam", bg=BG_INPUT,
                                 fg=ACCENT_CYAN, font=("Segoe UI", 9, "bold"), relief=tk.FLAT,
                                 padx=10, pady=4, cursor="hand2", command=self.toggle_aim)
        self.aim_btn.pack(side=tk.RIGHT)

        # Message Box
        tk.Label(card, text="Message to Transmit:", fg=TEXT_MAIN, bg=BG_CARD,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(8, 4))

        self.tx_input = tk.Text(card, height=4, bg=BG_INPUT, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
                                font=("Consolas", 11), relief=tk.FLAT, padx=8, pady=8,
                                highlightbackground=BORDER, highlightthickness=1)
        self.tx_input.pack(fill=tk.X, padx=14)
        self.tx_input.insert("1.0", "HELLO RECEIVER")
        self.tx_input.bind("<KeyRelease>", self._update_binary_preview)

        # Bit Timing Slider (Must match Receiver PC!)
        spd_frame = tk.Frame(card, bg=BG_CARD)
        spd_frame.pack(fill=tk.X, padx=14, pady=(10, 6))
        self.spd_lbl = tk.Label(spd_frame, text="Bit Duration: 45 ms (~22 bps)", fg=TEXT_MUTED,
                                bg=BG_CARD, font=("Consolas", 9))
        self.spd_lbl.pack(side=tk.LEFT)
        ttk.Scale(spd_frame, from_=5, to=500, variable=self.bit_speed, orient=tk.HORIZONTAL,
                  command=self._on_speed_change).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        # Transmit Button
        self.tx_btn = tk.Button(card, text="⚡ TRANSMIT BINARY OVER LASER", bg=ACCENT_RED, fg="#ffffff",
                                font=("Segoe UI", 10, "bold"), relief=tk.FLAT, pady=9, cursor="hand2",
                                command=self.send_transmission)
        self.tx_btn.pack(fill=tk.X, padx=14, pady=8)

        # Binary Frame Preview
        tk.Label(card, text="Encoded Binary Frames (Start[1] + 8-bit ASCII + Stop[0]):", fg=TEXT_MUTED,
                 bg=BG_CARD, font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(6, 2))

        self.bin_preview = scrolledtext.ScrolledText(card, height=8, bg=BG_INPUT, fg=ACCENT_CYAN,
                                                     font=("Consolas", 9), relief=tk.FLAT, state=tk.DISABLED,
                                                     highlightbackground=BORDER, highlightthickness=1)
        self.bin_preview.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))

        self._update_binary_preview()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_combo.current(0)

    def toggle_connection(self):
        if self.is_connected:
            self.is_connected = False
            if self.ser:
                self.ser.close()
            self.connect_btn.config(text="Connect", bg=ACCENT_CYAN)
            self.status_lbl.config(text="OFFLINE", fg=TEXT_MUTED)
        else:
            port = self.port_combo.get()
            if not port:
                messagebox.showwarning("No Port", "Select the Transmitter Arduino port first.")
                return
            try:
                self.ser = serial.Serial(port, 115200, timeout=0.1)
                time.sleep(1.5)
                self.is_connected = True
                self.connect_btn.config(text="Disconnect", bg="#da3633")
                self.status_lbl.config(text=f"ONLINE ({port})", fg=ACCENT_GREEN)
                self._send_serial(f"SPD:{self.bit_speed.get()}")
                threading.Thread(target=self._serial_reader, daemon=True).start()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _send_serial(self, msg):
        if self.is_connected and self.ser and self.ser.is_open:
            try:
                self.ser.write((msg + "\n").encode("utf-8"))
            except Exception:
                pass

    def _serial_reader(self):
        while self.is_connected and self.running:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                    if line == "TX_DONE":
                        self.root.after(0, lambda: self.tx_btn.config(
                            state=tk.NORMAL, text="⚡ TRANSMIT BINARY OVER LASER", bg=ACCENT_RED))
            except Exception:
                break

    def toggle_aim(self):
        if not self.is_connected:
            messagebox.showinfo("Not Connected", "Connect the Transmitter Arduino first.")
            return
        self.align_mode = not self.align_mode
        if self.align_mode:
            self._send_serial("ALIGN_ON")
            self.aim_btn.config(text="◉ Aiming Beam ON (Click to Off)", bg=ACCENT_RED, fg="#ffffff")
        else:
            self._send_serial("ALIGN_OFF")
            self.aim_btn.config(text="◎ Turn On Steady Aiming Beam", bg=BG_INPUT, fg=ACCENT_CYAN)

    def _on_speed_change(self, val):
        spd = int(float(val))
        bps = round(1000 / spd)
        self.spd_lbl.config(text=f"Bit Duration: {spd} ms (~{bps} bps)")
        self._send_serial(f"SPD:{spd}")

    def _update_binary_preview(self, event=None):
        text = self.tx_input.get("1.0", "end-1c")
        lines = [f"'{ch}'  ->  [1] {format(ord(ch), '08b')} [0]" for ch in text]
        self.bin_preview.config(state=tk.NORMAL)
        self.bin_preview.delete("1.0", tk.END)
        self.bin_preview.insert(tk.END, "\n".join(lines))
        self.bin_preview.config(state=tk.DISABLED)

    def send_transmission(self):
        if not self.is_connected:
            messagebox.showinfo("Not Connected", "Connect the Transmitter Arduino first.")
            return
        if self.align_mode:
            self.toggle_aim()  # Turn off steady beam before pulsing data
        msg = self.tx_input.get("1.0", "end-1c").replace("\n", " ")
        if not msg:
            return
        self.tx_btn.config(state=tk.DISABLED, text="PULSING LASER...", bg="#8b2626")
        self._send_serial(f"TX:{msg}")

    def on_close(self):
        self.running = False
        if self.is_connected:
            self._send_serial("ALIGN_OFF")
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = LaserTransmitterApp(root)
    root.mainloop()