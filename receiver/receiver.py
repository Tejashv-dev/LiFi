import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time
from collections import deque

BG_MAIN = "#0e1117"
BG_CARD = "#161b22"
BG_INPUT = "#0d1117"
BORDER = "#30363d"
SCROLL_THUMB = "#262c36"
SCROLL_HOVER = "#58a6ff"
TEXT_MAIN = "#e6edf3"
TEXT_MUTED = "#8b949e"
ACCENT_RED = "#ff3b3b"
ACCENT_CYAN = "#58a6ff"
ACCENT_GREEN = "#3fb950"


class MinimalScrolledText(tk.Frame):
    """Drop-in replacement for ScrolledText with a flat, arrowless dark scrollbar."""
    def __init__(self, parent, **text_kwargs):
        super().__init__(parent, bg=BG_INPUT, highlightbackground=BORDER, highlightthickness=1)

        text_kwargs.pop("highlightbackground", None)
        text_kwargs.pop("highlightthickness", None)

        self.text = tk.Text(self, **text_kwargs)
        self.vbar = ttk.Scrollbar(self, orient=tk.VERTICAL, style="Minimal.Vertical.TScrollbar",
                                  command=self.text.yview)
        self.text.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Explicitly delegate Text methods (avoids __getattr__ recursion during ttk init)
        for method in ("insert", "get", "delete", "see", "bind", "index"):
            setattr(self, method, getattr(self.text, method))

    def config(self, **kwargs):
        self.text.config(**kwargs)

    configure = config

class LaserReceiverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OPTICAL RX — LDR Receiver & Decoder Console")
        self.root.geometry("680x680")
        self.root.configure(bg=BG_MAIN)

        self.ser = None
        self.is_connected = False
        self.running = True
        self.ldr_history = deque([0] * 200, maxlen=200)
        self.threshold = tk.IntVar(value=550)
        self.bit_speed = tk.IntVar(value=45)
        self.current_ldr = 0
        self.known_ports = []

        self._setup_styles()
        self._build_ui()
        self._auto_refresh_ports()
        self._update_oscilloscope()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_CARD,
                        foreground=TEXT_MAIN, arrowcolor=TEXT_MAIN, bordercolor=BORDER)
        style.configure("Horizontal.TScale", background=BG_CARD, troughcolor=BG_INPUT)

        # Remove top/bottom scrollbar arrows for a minimal pill-style thumb
        style.layout("Minimal.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {
                "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                "sticky": "ns"
            })
        ])
        style.configure("Minimal.Vertical.TScrollbar",
                        gripcount=0,
                        background=SCROLL_THUMB,
                        troughcolor=BG_INPUT,
                        bordercolor=BG_INPUT,
                        lightcolor=SCROLL_THUMB,
                        darkcolor=SCROLL_THUMB,
                        width=8)
        style.map("Minimal.Vertical.TScrollbar",
                  background=[("active", SCROLL_HOVER), ("pressed", ACCENT_CYAN)])

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

        self.port_combo = ttk.Combobox(top_bar, width=16, state="readonly", font=("Consolas", 9))
        self.port_combo.pack(side=tk.RIGHT, padx=4, pady=8)

        tk.Label(top_bar, text="Auto-Port:", fg=TEXT_MUTED, bg=BG_CARD,
                 font=("Segoe UI", 8)).pack(side=tk.RIGHT, padx=(4, 0))

        # Main Vertical Resizable PanedWindow
        self.main_paned = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg=BORDER,
                                         sashwidth=6, sashrelief=tk.FLAT, bd=0)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 14))

        # --- TOP PANE: Decoded Output Card ---
        rx_card = tk.Frame(self.main_paned, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)

        rx_hdr = tk.Frame(rx_card, bg=BG_CARD)
        rx_hdr.pack(fill=tk.X, padx=14, pady=(10, 4))
        tk.Label(rx_hdr, text="DECODED BINARY & MESSAGE (Drag borders to resize)", fg=ACCENT_CYAN,
                 bg=BG_CARD, font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        tk.Button(rx_hdr, text="Clear", bg=BG_INPUT, fg=TEXT_MUTED, font=("Segoe UI", 8),
                  relief=tk.FLAT, padx=10, cursor="hand2", command=self.clear_rx).pack(side=tk.RIGHT)

        # Horizontal PanedWindow to resize Binary Log vs Decoded Text
        self.rx_split = tk.PanedWindow(rx_card, orient=tk.HORIZONTAL, bg=BORDER,
                                       sashwidth=5, sashrelief=tk.FLAT, bd=0)
        self.rx_split.pack(fill=tk.BOTH, expand=True, padx=14, pady=(2, 14))

        bin_frame = tk.Frame(self.rx_split, bg=BG_CARD)
        txt_frame = tk.Frame(self.rx_split, bg=BG_CARD)

        self.rx_bin_box = MinimalScrolledText(bin_frame, width=20, height=12, bg=BG_INPUT,
                                              fg=TEXT_MUTED, font=("Consolas", 9), relief=tk.FLAT,
                                              state=tk.DISABLED, padx=8, pady=6)
        self.rx_bin_box.pack(fill=tk.BOTH, expand=True)

        self.rx_text_box = MinimalScrolledText(txt_frame, width=38, height=12, bg=BG_INPUT,
                                               fg=ACCENT_GREEN, font=("Consolas", 14, "bold"),
                                               relief=tk.FLAT, state=tk.DISABLED, padx=10, pady=8)
        self.rx_text_box.pack(fill=tk.BOTH, expand=True)

        self.rx_split.add(bin_frame, minsize=130, stretch="never")
        self.rx_split.add(txt_frame, minsize=260, stretch="always")

        # --- BOTTOM PANE: Oscilloscope & Timing Card ---
        scope_card = tk.Frame(self.main_paned, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)

        scope_hdr = tk.Frame(scope_card, bg=BG_CARD)
        scope_hdr.pack(fill=tk.X, padx=14, pady=(8, 2))
        tk.Label(scope_hdr, text="LIVE LDR SIGNAL (PIN A0)", fg=ACCENT_GREEN, bg=BG_CARD,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.adc_lbl = tk.Label(scope_hdr, text="ADC: 0000", fg=TEXT_MAIN, bg=BG_CARD,
                                font=("Consolas", 10, "bold"))
        self.adc_lbl.pack(side=tk.RIGHT)

        self.scope_canvas = tk.Canvas(scope_card, bg=BG_INPUT, height=95,
                                      highlightbackground=BORDER, highlightthickness=1)
        self.scope_canvas.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)

        # Threshold Slider + Direct Entry
        th_frame = tk.Frame(scope_card, bg=BG_CARD)
        th_frame.pack(fill=tk.X, padx=14, pady=(4, 2))
        tk.Label(th_frame, text="Threshold:", fg=ACCENT_RED,
                 bg=BG_CARD, font=("Consolas", 9, "bold")).pack(side=tk.LEFT)

        self.th_entry = tk.Entry(th_frame, width=6, bg=BG_INPUT, fg=ACCENT_RED,
                                 insertbackground=TEXT_MAIN, font=("Consolas", 9, "bold"),
                                 relief=tk.FLAT, justify="center",
                                 highlightbackground=BORDER, highlightthickness=1)
        self.th_entry.pack(side=tk.LEFT, padx=(6, 10), ipady=2)
        self.th_entry.insert(0, "550")
        self.th_entry.bind("<Return>", self._on_threshold_entry)
        self.th_entry.bind("<FocusOut>", self._on_threshold_entry)

        ttk.Scale(th_frame, from_=50, to=980, variable=self.threshold, orient=tk.HORIZONTAL,
                  command=self._on_threshold_slider).pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # Bit Timing Slider + Direct Entry
        spd_frame = tk.Frame(scope_card, bg=BG_CARD)
        spd_frame.pack(fill=tk.X, padx=14, pady=(2, 10))
        self.spd_lbl = tk.Label(spd_frame, text="Bit Delay (ms) [~22 bps]:", fg=TEXT_MUTED,
                                bg=BG_CARD, font=("Consolas", 9))
        self.spd_lbl.pack(side=tk.LEFT)

        self.spd_entry = tk.Entry(spd_frame, width=6, bg=BG_INPUT, fg=ACCENT_CYAN,
                                  insertbackground=TEXT_MAIN, font=("Consolas", 9, "bold"),
                                  relief=tk.FLAT, justify="center",
                                  highlightbackground=BORDER, highlightthickness=1)
        self.spd_entry.pack(side=tk.LEFT, padx=(6, 10), ipady=2)
        self.spd_entry.insert(0, "45")
        self.spd_entry.bind("<Return>", self._on_speed_entry)
        self.spd_entry.bind("<FocusOut>", self._on_speed_entry)

        ttk.Scale(spd_frame, from_=5, to=500, variable=self.bit_speed, orient=tk.HORIZONTAL,
                  command=self._on_speed_slider).pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self.main_paned.add(rx_card, minsize=240, stretch="always")
        self.main_paned.add(scope_card, minsize=170, stretch="never")

    def _auto_refresh_ports(self):
        if not self.running:
            return
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports != self.known_ports:
            current_selection = self.port_combo.get()
            self.known_ports = ports
            self.port_combo["values"] = ports
            if current_selection in ports:
                self.port_combo.set(current_selection)
            elif ports:
                self.port_combo.current(0)
            else:
                self.port_combo.set("")
        self.root.after(1500, self._auto_refresh_ports)

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

    def _apply_threshold(self, th):
        th = max(10, min(1020, th))
        self.threshold.set(th)
        self.th_entry.delete(0, tk.END)
        self.th_entry.insert(0, str(th))
        self._send_serial(f"TH:{th}")

    def _on_threshold_slider(self, val):
        self._apply_threshold(int(float(val)))

    def _on_threshold_entry(self, event=None):
        try:
            val = int(self.th_entry.get().strip())
            self._apply_threshold(val)
        except ValueError:
            self.th_entry.delete(0, tk.END)
            self.th_entry.insert(0, str(self.threshold.get()))

    def _apply_speed(self, spd):
        spd = max(5, min(500, spd))
        self.bit_speed.set(spd)
        bps = round(1000 / spd)
        self.spd_lbl.config(text=f"Bit Delay (ms) [~{bps} bps]:")
        self.spd_entry.delete(0, tk.END)
        self.spd_entry.insert(0, str(spd))
        self._send_serial(f"SPD:{spd}")

    def _on_speed_slider(self, val):
        self._apply_speed(int(float(val)))

    def _on_speed_entry(self, event=None):
        try:
            val = int(self.spd_entry.get().strip())
            self._apply_speed(val)
        except ValueError:
            self.spd_entry.delete(0, tk.END)
            self.spd_entry.insert(0, str(self.bit_speed.get()))

    def _append_received_byte(self, byte_val):
        bits = format(byte_val, "08b")

        self.rx_bin_box.config(state=tk.NORMAL)
        self.rx_text_box.config(state=tk.NORMAL)

        if byte_val in (8, 127):  # Backspace / Delete
            self.rx_bin_box.insert(tk.END, f"{bits} (<BS>)\n")
            current_text = self.rx_text_box.get("1.0", "end-1c")
            if current_text:
                self.rx_text_box.delete("end-2c", "end-1c")
        elif byte_val in (10, 13):  # Enter / Newline
            self.rx_bin_box.insert(tk.END, f"{bits} (\\n)\n")
            self.rx_text_box.insert(tk.END, "\n")
        else:
            char = chr(byte_val) if 32 <= byte_val <= 126 else "?"
            self.rx_bin_box.insert(tk.END, f"{bits} ({char})\n")
            self.rx_text_box.insert(tk.END, char)

        self.rx_bin_box.see(tk.END)
        self.rx_text_box.see(tk.END)
        self.rx_bin_box.config(state=tk.DISABLED)
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
        h = c.winfo_height() or 95

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