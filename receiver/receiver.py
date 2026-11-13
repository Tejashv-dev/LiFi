import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import time
from collections import deque

BG_MAIN = "#0e1117"
BG_CARD = "#161b22"
BG_INPUT = "#0d1117"
BORDER = "#30363d"
TEXT_MAIN = "#e6edf3"
TEXT_MUTED = "#8b949e"
ACCENT_RED = "#ff3b3b"
ACCENT_CYAN = "#58a6ff"
ACCENT_GREEN = "#3fb950"


class LaserReceiverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OPTICAL RX — LDR Receiver & Decoder Console")
        self.root.geometry("620x620")
        self.root.configure(bg=BG_MAIN)

        self.ser = None
        self.is_connected = False
        self.running = True
        self.ldr_history = deque([0] * 200, maxlen=200)
        self.threshold = tk.IntVar(value=550)
        self.bit_speed = tk.IntVar(value=45)
        self.current_ldr = 0

        self._setup_styles()
        self._build_ui()
        self.refresh_ports()
        self._update_oscilloscope()
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

        tk.Label(top_bar, text="● LASER RX", fg=ACCENT_GREEN, bg=BG_CARD,
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

        # Oscilloscope Card
        scope_card = tk.Frame(self.root, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        scope_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        scope_hdr = tk.Frame(scope_card, bg=BG_CARD)
        scope_hdr.pack(fill=tk.X, padx=14, pady=(10, 4))
        tk.Label(scope_hdr, text="LIVE LDR SIGNAL (PIN A0)", fg=ACCENT_GREEN, bg=BG_CARD,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.adc_lbl = tk.Label(scope_hdr, text="ADC: 0000", fg=TEXT_MAIN, bg=BG_CARD,
                                font=("Consolas", 10, "bold"))
        self.adc_lbl.pack(side=tk.RIGHT)

        self.scope_canvas = tk.Canvas(scope_card, bg=BG_INPUT, height=170,
                                      highlightbackground=BORDER, highlightthickness=1)
        self.scope_canvas.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)

        # Threshold Slider
        th_frame = tk.Frame(scope_card, bg=BG_CARD)
        th_frame.pack(fill=tk.X, padx=14, pady=(6, 4))
        self.th_lbl = tk.Label(th_frame, text="Trigger Threshold: 550", fg=ACCENT_RED,
                               bg=BG_CARD, font=("Consolas", 9, "bold"))
        self.th_lbl.pack(side=tk.LEFT)
        ttk.Scale(th_frame, from_=50, to=980, variable=self.threshold, orient=tk.HORIZONTAL,
                  command=self._on_threshold_change).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        # Bit Timing Slider (Must match Transmitter PC!)
        spd_frame = tk.Frame(scope_card, bg=BG_CARD)
        spd_frame.pack(fill=tk.X, padx=14, pady=(2, 12))
        self.spd_lbl = tk.Label(spd_frame, text="Bit Duration: 45 ms (~22 bps)", fg=TEXT_MUTED,
                                bg=BG_CARD, font=("Consolas", 9))
        self.spd_lbl.pack(side=tk.LEFT)
        ttk.Scale(spd_frame, from_=20, to=120, variable=self.bit_speed, orient=tk.HORIZONTAL,
                  command=self._on_speed_change).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))

        # Decoded Output Card
        rx_card = tk.Frame(self.root, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        rx_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=(6, 14))

        rx_hdr = tk.Frame(rx_card, bg=BG_CARD)
        rx_hdr.pack(fill=tk.X, padx=14, pady=(10, 4))
        tk.Label(rx_hdr, text="DECODED BINARY & MESSAGE", fg=ACCENT_CYAN, bg=BG_CARD,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(rx_hdr, text="Clear", bg=BG_INPUT, fg=TEXT_MUTED, font=("Segoe UI", 8),
                  relief=tk.FLAT, padx=10, cursor="hand2", command=self.clear_rx).pack(side=tk.RIGHT)

        split = tk.Frame(rx_card, bg=BG_CARD)
        split.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=2)
        split.rowconfigure(0, weight=1)

        self.rx_bin_box = scrolledtext.ScrolledText(split, height=7, bg=BG_INPUT, fg=TEXT_MUTED,
                                                    font=("Consolas", 9), relief=tk.FLAT, state=tk.DISABLED,
                                                    highlightbackground=BORDER, highlightthickness=1)
        self.rx_bin_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        self.rx_text_box = scrolledtext.ScrolledText(split, height=7, bg=BG_INPUT, fg=ACCENT_GREEN,
                                                     font=("Consolas", 13, "bold"), relief=tk.FLAT, state=tk.DISABLED,
                                                     highlightbackground=BORDER, highlightthickness=1)
        self.rx_text_box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

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
                messagebox.showwarning("No Port", "Select the Receiver Arduino port first.")
                return
            try:
                self.ser = serial.Serial(port, 115200, timeout=0.1)
                time.sleep(1.5)
                self.is_connected = True
                self.connect_btn.config(text="Disconnect", bg="#da3633")
                self.status_lbl.config(text=f"ONLINE ({port})", fg=ACCENT_GREEN)
                self._send_serial(f"TH:{self.threshold.get()}")
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
                    if line.startswith("LDR:"):
                        val = int(line[4:])
                        self.current_ldr = val
                        self.ldr_history.append(val)
                    elif line.startswith("RX:"):
                        byte_val = int(line[3:])
                        self.root.after(0, self._append_received_byte, byte_val)
            except Exception:
                break

    def _on_threshold_change(self, val):
        th = int(float(val))
        self.th_lbl.config(text=f"Trigger Threshold: {th}")
        self._send_serial(f"TH:{th}")

    def _on_speed_change(self, val):
        spd = int(float(val))
        bps = round(1000 / spd)
        self.spd_lbl.config(text=f"Bit Duration: {spd} ms (~{bps} bps)")
        self._send_serial(f"SPD:{spd}")

    def _append_received_byte(self, byte_val):
        bits = format(byte_val, "08b")
        char = chr(byte_val) if 32 <= byte_val <= 126 else "?"

        self.rx_bin_box.config(state=tk.NORMAL)
        self.rx_bin_box.insert(tk.END, f"{bits} ({char})\n")
        self.rx_bin_box.see(tk.END)
        self.rx_bin_box.config(state=tk.DISABLED)

        self.rx_text_box.config(state=tk.NORMAL)
        self.rx_text_box.insert(tk.END, char)
        self.rx_text_box.see(tk.END)
        self.rx_text_box.config(state=tk.DISABLED)

    def clear_rx(self):
        for box in (self.rx_bin_box, self.rx_text_box):
            box.config(state=tk.NORMAL)
            box.delete("1.0", tk.END)
            box.config(state=tk.DISABLED)

    def _update_oscilloscope(self):
        if not self.running:
            return
        self.adc_lbl.config(text=f"ADC: {self.current_ldr:04d}")
        c = self.scope_canvas
        c.delete("all")
        w = c.winfo_width() or 400
        h = c.winfo_height() or 170

        for i in range(1, 4):
            y = h * i / 4
            c.create_line(0, y, w, y, fill="#1f242c", dash=(2, 4))

        th_y = h - (self.threshold.get() / 1023.0) * h
        c.create_line(0, th_y, w, th_y, fill=ACCENT_RED, dash=(6, 4), width=1.5)

        points = []
        step = w / max(1, len(self.ldr_history) - 1)
        for idx, val in enumerate(self.ldr_history):
            x = idx * step
            y = h - (val / 1023.0) * h
            points.extend([x, y])

        if len(points) >= 4:
            c.create_line(points, fill=ACCENT_GREEN, width=2, smooth=True)

        self.root.after(30, self._update_oscilloscope)

    def on_close(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = LaserReceiverApp(root)
    root.mainloop()