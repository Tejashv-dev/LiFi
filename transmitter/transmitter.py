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
ACCENT_ORANGE = "#d29922"


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

class LaserTransmitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("OPTICAL TX — Laser Transmitter Console")
        self.root.geometry("560x620")
        self.root.configure(bg=BG_MAIN)

        self.ser = None
        self.is_connected = False
        self.running = True
        self.align_mode = False
        self.live_mode = False
        self.bit_speed = tk.IntVar(value=45)
        self.known_ports = []

        self.live_queue = deque()
        self.tx_busy = False

        self._setup_styles()
        self._build_ui()
        self._auto_refresh_ports()
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

        tk.Label(top_bar, text="● LASER TX", fg=ACCENT_RED, bg=BG_CARD,
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

        # Resizable PanedWindow
        self.paned = tk.PanedWindow(self.root, orient=tk.VERTICAL, bg=BORDER,
                                    sashwidth=5, sashrelief=tk.FLAT, bd=0)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 14))

        top_card = tk.Frame(self.paned, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        bottom_card = tk.Frame(self.paned, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self.paned.add(top_card, minsize=250, stretch="always")
        self.paned.add(bottom_card, minsize=120, stretch="always")

        # Aiming Laser & Mode Toggle Row
        ctrl_frame = tk.Frame(top_card, bg=BG_CARD)
        ctrl_frame.pack(fill=tk.X, padx=14, pady=(12, 6))

        self.mode_btn = tk.Button(ctrl_frame, text="⇄ Mode: BATCH (Click for Live)", bg=BG_INPUT,
                                  fg=ACCENT_ORANGE, font=("Segoe UI", 9, "bold"), relief=tk.FLAT,
                                  padx=10, pady=4, cursor="hand2", command=self.toggle_live_mode)
        self.mode_btn.pack(side=tk.LEFT)

        self.aim_btn = tk.Button(ctrl_frame, text="◎ Steady Aiming Beam", bg=BG_INPUT,
                                 fg=ACCENT_CYAN, font=("Segoe UI", 9, "bold"), relief=tk.FLAT,
                                 padx=10, pady=4, cursor="hand2", command=self.toggle_aim)
        self.aim_btn.pack(side=tk.RIGHT)

        # Message Box (Now using MinimalScrolledText)
        self.msg_hdr_lbl = tk.Label(top_card, text="Message to Transmit (Batch Mode):", fg=TEXT_MAIN,
                                    bg=BG_CARD, font=("Segoe UI", 9, "bold"))
        self.msg_hdr_lbl.pack(anchor="w", padx=14, pady=(6, 4))

        self.tx_input = MinimalScrolledText(top_card, height=4, bg=BG_INPUT, fg=TEXT_MAIN,
                                            insertbackground=TEXT_MAIN, font=("Consolas", 11),
                                            relief=tk.FLAT, padx=8, pady=8)
        self.tx_input.pack(fill=tk.BOTH, expand=True, padx=14)
        self.tx_input.insert("1.0", "HELLO RECEIVER")
        self.tx_input.bind("<KeyPress>", self._on_key_press)
        self.tx_input.bind("<KeyRelease>", self._update_binary_preview)

        # Bit Timing Slider + Manual Entry
        spd_frame = tk.Frame(top_card, bg=BG_CARD)
        spd_frame.pack(fill=tk.X, padx=14, pady=(10, 6))

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

        self.spd_scale = ttk.Scale(spd_frame, from_=5, to=500, variable=self.bit_speed,
                                   orient=tk.HORIZONTAL, command=self._on_speed_slider)
        self.spd_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # Transmit Button
        self.tx_btn = tk.Button(top_card, text="⚡ TRANSMIT BINARY OVER LASER", bg=ACCENT_RED, fg="#ffffff",
                                font=("Segoe UI", 10, "bold"), relief=tk.FLAT, pady=8, cursor="hand2",
                                command=self.send_transmission)
        self.tx_btn.pack(fill=tk.X, padx=14, pady=(4, 12))

        # Binary Frame Preview (Bottom Pane)
        tk.Label(bottom_card, text="Encoded Binary Frames (Start[1] + 8-bit ASCII + Stop[0]):",
                 fg=TEXT_MUTED, bg=BG_CARD, font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(8, 2))

        self.bin_preview = MinimalScrolledText(bottom_card, height=6, bg=BG_INPUT, fg=ACCENT_CYAN,
                                               font=("Consolas", 9), relief=tk.FLAT, state=tk.DISABLED,
                                               padx=8, pady=6)
        self.bin_preview.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))

        self._update_binary_preview()

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
                        self.root.after(0, self._on_tx_done)
            except Exception:
                break

    def _on_tx_done(self):
        if self.live_mode:
            if self.live_queue:
                next_byte = self.live_queue.popleft()
                self._send_serial(f"TXB:{next_byte}")
            else:
                self.tx_busy = False
        else:
            self.tx_btn.config(state=tk.NORMAL, text="⚡ TRANSMIT BINARY OVER LASER", bg=ACCENT_RED)

    def toggle_live_mode(self):
        self.live_mode = not self.live_mode
        self.live_queue.clear()
        self.tx_busy = False
        if self.live_mode:
            self.mode_btn.config(text="⚡ Mode: LIVE STREAM (Active)", bg=ACCENT_GREEN, fg="#000000")
            self.msg_hdr_lbl.config(text="Live Typing Console (Keystrokes & Backspace pulse immediately):",
                                    fg=ACCENT_GREEN)
            self.tx_btn.config(state=tk.DISABLED, text="LIVE TYPING MODE ACTIVE", bg=BORDER)
        else:
            self.mode_btn.config(text="⇄ Mode: BATCH (Click for Live)", bg=BG_INPUT, fg=ACCENT_ORANGE)
            self.msg_hdr_lbl.config(text="Message to Transmit (Batch Mode):", fg=TEXT_MAIN)
            self.tx_btn.config(state=tk.NORMAL, text="⚡ TRANSMIT BINARY OVER LASER", bg=ACCENT_RED)

    def _on_key_press(self, event):
        if not self.live_mode or not self.is_connected:
            return
        if self.align_mode:
            self.toggle_aim()

        byte_val = None
        if event.keysym == "BackSpace":
            byte_val = 8
        elif event.keysym in ("Return", "KP_Enter"):
            byte_val = 10
        elif event.char and 32 <= ord(event.char) <= 126:
            byte_val = ord(event.char)

        if byte_val is not None:
            self._queue_live_byte(byte_val)

    def _queue_live_byte(self, byte_val):
        if not self.tx_busy:
            self.tx_busy = True
            self._send_serial(f"TXB:{byte_val}")
            est_ms = int(self.bit_speed.get() * 11)
            self.root.after(est_ms, self._live_watchdog)
        else:
            self.live_queue.append(byte_val)

    def _live_watchdog(self):
        if self.live_mode and self.tx_busy:
            self._on_tx_done()

    def toggle_aim(self):
        if not self.is_connected:
            messagebox.showinfo("Not Connected", "Connect the Transmitter Arduino first.")
            return
        self.align_mode = not self.align_mode
        if self.align_mode:
            self._send_serial("ALIGN_ON")
            self.aim_btn.config(text="◉ Aiming Beam ON", bg=ACCENT_RED, fg="#ffffff")
        else:
            self._send_serial("ALIGN_OFF")
            self.aim_btn.config(text="◎ Steady Aiming Beam", bg=BG_INPUT, fg=ACCENT_CYAN)

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

    def _update_binary_preview(self, event=None):
        text = self.tx_input.get("1.0", "end-1c")
        lines = []
        for ch in text:
            label = "\\n" if ch == "\n" else ch
            lines.append(f"'{label}'  ->  [1] {format(ord(ch), '08b')} [0]")
        self.bin_preview.config(state=tk.NORMAL)
        self.bin_preview.delete("1.0", tk.END)
        self.bin_preview.insert(tk.END, "\n".join(lines))
        self.bin_preview.see(tk.END)
        self.bin_preview.config(state=tk.DISABLED)

    def send_transmission(self):
        if self.live_mode:
            return
        if not self.is_connected:
            messagebox.showinfo("Not Connected", "Connect the Transmitter Arduino first.")
            return
        if self.align_mode:
            self.toggle_aim()
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