#!/usr/bin/env python3
"""
Open Deck - serial mirror GUI

Mirrors the same 2x4 key grid + encoder readout that the physical OLED
shows, but rendered natively on your laptop instead of pushed over I2C.
Purpose: isolate whether display "lag" is the I2C/SH1106 bus being slow,
or something upstream in the firmware's scan loop. If this window reacts
instantly to rapid button mashing while the physical OLED still visibly
lags, that proves it's specifically the I2C push - not the scan/firmware
logic feeding it.

Usage:
    python3 serial_mirror_gui.py [--port /dev/cu.usbmodemXXXX]

If --port is omitted, it auto-detects the first /dev/cu.usbmodem* device
and reconnects automatically if the board drops off USB (which this board
has done a lot) - no need to restart the script when that happens.
"""

import argparse
import glob
import queue
import re
import threading
import time
import tkinter as tk

import serial

KEY_LAYOUT = [
    ["TERM", "ENTR", "FOX", "OWL"],
    ["MIC", "X", "CAT", "PNDA"],
]

KEY_RE = re.compile(r"KEY\s+(\S+)\s+(DOWN|up)")
ENC_RE = re.compile(r"encoder dir=(-?\d+) count=(-?\d+)")


def find_port():
    matches = glob.glob("/dev/cu.usbmodem*")
    return matches[0] if matches else None


class SerialReader(threading.Thread):
    """Background thread: owns the serial connection, reconnects on drop,
    pushes (event_dict, wall_clock_time) tuples into a queue for the GUI
    thread to consume. Never touches Tkinter directly (not thread-safe)."""

    def __init__(self, port, out_queue):
        super().__init__(daemon=True)
        self.port = port
        self.out_queue = out_queue
        self.running = True

    def run(self):
        while self.running:
            port = self.port or find_port()
            if not port:
                self.out_queue.put(({"type": "status", "text": "no board found, retrying..."}, time.time()))
                time.sleep(1)
                continue
            try:
                with serial.Serial(port, 115200, timeout=0.5) as ser:
                    self.out_queue.put(({"type": "status", "text": f"connected: {port}"}, time.time()))
                    while self.running:
                        line = ser.readline().decode(errors="replace").strip()
                        if not line:
                            continue
                        now = time.time()
                        m = KEY_RE.search(line)
                        if m:
                            self.out_queue.put(({"type": "key", "name": m.group(1), "state": m.group(2)}, now))
                            continue
                        m = ENC_RE.search(line)
                        if m:
                            self.out_queue.put(({"type": "encoder", "count": int(m.group(2))}, now))
                            continue
            except serial.SerialException:
                self.out_queue.put(({"type": "status", "text": "disconnected, retrying..."}, time.time()))
                time.sleep(1)


class MirrorGUI:
    def __init__(self, root, out_queue):
        self.root = root
        self.q = out_queue
        self.last_event_time = None
        self.boxes = {}

        root.title("Open Deck - serial mirror (no I2C bottleneck)")
        root.configure(bg="#111")
        root.geometry("420x260")

        self.status_var = tk.StringVar(value="starting...")
        tk.Label(root, textvariable=self.status_var, fg="#888", bg="#111", font=("Menlo", 10)).pack(pady=(8, 2))

        self.encoder_var = tk.StringVar(value="encoder: 0")
        tk.Label(root, textvariable=self.encoder_var, fg="white", bg="#111", font=("Menlo", 16, "bold")).pack(pady=4)

        self.latency_var = tk.StringVar(value="last event: -- ms ago")
        tk.Label(root, textvariable=self.latency_var, fg="#0f0", bg="#111", font=("Menlo", 12)).pack(pady=(0, 8))

        grid = tk.Frame(root, bg="#111")
        grid.pack(padx=10, pady=10)

        for r, row in enumerate(KEY_LAYOUT):
            for c, name in enumerate(row):
                box = tk.Label(
                    grid, text=name, width=8, height=3,
                    bg="#222", fg="white", font=("Menlo", 11, "bold"),
                    relief="solid", bd=1,
                )
                box.grid(row=r, column=c, padx=3, pady=3)
                self.boxes[name] = box

        self._poll()
        self._tick_latency()

        # macOS Tk sometimes paints a blank window until it gets a resize/
        # focus kick - force one right after the initial layout.
        root.update_idletasks()
        root.lift()
        root.attributes("-topmost", True)
        root.after(200, lambda: root.attributes("-topmost", False))
        root.after(50, lambda: root.geometry("421x260"))
        root.after(100, lambda: root.geometry("420x260"))

    def _poll(self):
        try:
            while True:
                event, t = self.q.get_nowait()
                self._handle(event, t)
        except queue.Empty:
            pass
        self.root.after(4, self._poll)  # ~250Hz poll, far tighter than anything I2C can do

    def _handle(self, event, t):
        self.last_event_time = t
        if event["type"] == "status":
            self.status_var.set(event["text"])
        elif event["type"] == "key":
            box = self.boxes.get(event["name"])
            if box:
                if event["state"] == "DOWN":
                    box.configure(bg="white", fg="black")
                else:
                    box.configure(bg="#222", fg="white")
        elif event["type"] == "encoder":
            self.encoder_var.set(f"encoder: {event['count']}")

    def _tick_latency(self):
        if self.last_event_time is not None:
            ms = (time.time() - self.last_event_time) * 1000
            self.latency_var.set(f"last event: {ms:5.0f} ms ago")
        self.root.after(50, self._tick_latency)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, help="Serial port (default: auto-detect /dev/cu.usbmodem*)")
    args = ap.parse_args()

    q = queue.Queue()
    reader = SerialReader(args.port, q)
    reader.start()

    root = tk.Tk()
    MirrorGUI(root, q)
    root.mainloop()
    reader.running = False


if __name__ == "__main__":
    main()
