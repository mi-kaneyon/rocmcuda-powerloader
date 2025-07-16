import os
import sys
import time
import subprocess
import threading
import hashlib
import json
import re
import tkinter as tk
from tkinter import ttk, messagebox
import signal

def create_test_file(file_path, text="Sample text for USB transfer verification. " * 2):
    try:
        with open(file_path, 'w') as f: f.write(text[:100])
    except Exception as e:
        print(f"[ERROR] Failed to create test file: {e}", file=sys.stderr, flush=True)

def calculate_hash(file_path):
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""): hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"[ERROR] Failed to calculate hash for {file_path}: {e}", file=sys.stderr, flush=True)
        return None

class StorageTest:
    def __init__(self, gui_callback=None):
        self.stop_event = threading.Event()
        self.gui_callback = gui_callback
        self.storage_mounts = []
        self.overall_success = False

    def _update_status(self, message):
        if self.gui_callback: self.gui_callback(message)
        else: print(message, flush=True)

    def detect_devices(self):
        self.storage_mounts = []
        try:
            lsblk_output = subprocess.check_output(["lsblk", "-J", "-p", "-o", "NAME,MOUNTPOINT,TRAN"], stderr=subprocess.DEVNULL, text=True)
            data = json.loads(lsblk_output)
            for dev in data.get("blockdevices", []):
                if dev.get("tran") == "usb" and dev.get("children"):
                    for part in dev["children"]:
                        mp = part.get("mountpoint")
                        if mp and mp not in self.storage_mounts: self.storage_mounts.append(mp)
            self._update_status(f"[INFO] lsblk: Found {len(self.storage_mounts)} mounted USB storage: {self.storage_mounts}")
        except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            self._update_status(f"[WARN] lsblk command failed or returned invalid data: {e}. Storage R/W test may be skipped.")

    def get_summary(self, total_cycles, total_failures):
        return f"[SUMMARY] Storage/USB Test: Cycles={total_cycles}, Success={total_cycles - total_failures}, Failures={total_failures}"
    
    def run_test_loop(self, progress_callback, duration=300):
        self._update_status("[INFO] Starting USB storage R/W test loop...")
        self.stop_event.clear(); self.overall_success = False
        self.detect_devices()
        if not self.storage_mounts:
            self._update_status("[WARN] No mounted USB storage found for R/W test. Test will be skipped.")
            return True
        
        source_file = "/tmp/source_test_file.txt"
        create_test_file(source_file)
        start_time = time.time(); total_cycles = 0; total_failures = 0

        while time.time() - start_time < duration and not self.stop_event.is_set():
            total_cycles += 1
            self._update_status(f"--- Cycle {total_cycles} (Time left: {int(duration - (time.time() - start_time))}s) ---")
            
            cycle_results = []
            threads = []
            def cycle_task(func, *args):
                cycle_results.append(func(*args))

            for mp in self.storage_mounts:
                t = threading.Thread(target=cycle_task, args=(self.perform_storage_test_cycle, mp, source_file)); threads.append(t); t.start()
            for t in threads: t.join()

            if False in cycle_results: total_failures += 1
            if progress_callback: progress_callback(0, ((time.time() - start_time) / duration) * 100)
            if self.stop_event.wait(timeout=2): break

        try:
            if os.path.exists(source_file): os.remove(source_file)
        except OSError as e: self._update_status(f"[WARN] Could not remove temp file {source_file}: {e}")
        
        self._update_status(self.get_summary(total_cycles, total_failures))
        self.overall_success = (total_cycles > 0 and total_failures == 0)
        return self.overall_success

    def perform_storage_test_cycle(self, mountpoint, source_file):
        target_file = os.path.join(mountpoint, "test_copy.txt")
        try:
            subprocess.check_call(["cp", source_file, target_file], stderr=subprocess.DEVNULL)
            source_hash, target_hash = calculate_hash(source_file), calculate_hash(target_file)
            if source_hash and target_hash and source_hash == target_hash:
                self._update_status(f"[INFO] R/W test PASS on {mountpoint}"); return True
            else:
                self._update_status(f"[ERROR] Hash mismatch on {mountpoint}"); return False
        except Exception as e:
            self._update_status(f"[ERROR] File transfer failed on {mountpoint}: {e}"); return False
        finally:
            if os.path.exists(target_file):
                try: os.remove(target_file)
                except OSError: pass

    def stop_test(self):
        self.stop_event.set(); self._update_status("[INFO] Storage test stop signal sent.")

# (以降のコードは変更ありません)
class StorageTestApp:
    def __init__(self, root):
        self.root = root; self.root.title("USB Port and Storage Test"); self.root.geometry("800x600")
        self.storage_test = StorageTest(gui_callback=self.update_status); self.device_details_frame = tk.Frame(root)
        self.device_details_frame.pack(padx=10, pady=10, fill="x"); self.controls_frame = tk.Frame(root)
        self.controls_frame.pack(pady=10)
        self.start_button = ttk.Button(self.controls_frame, text="Detect Devices", command=self.display_device_status); self.start_button.grid(row=0, column=0, padx=10)
        self.test_button = ttk.Button(self.controls_frame, text="Start Test", command=self._run_and_close, state="disabled"); self.test_button.grid(row=0, column=1, padx=10)
        self.stop_button = ttk.Button(self.controls_frame, text="Stop Test", command=self.stop_storage_test); self.stop_button.grid(row=0, column=2, padx=10)
        self.status_area = tk.Text(root, height=10, width=80, font=("Helvetica", 10)); self.status_area.pack(pady=10, expand=True, fill=tk.BOTH)
    def update_status(self, message):
        if self.root.winfo_exists(): self.status_area.insert(tk.END, str(message) + "\n"); self.status_area.see(tk.END)
    def display_device_status(self):
        self.storage_test.detect_devices();
        for widget in self.device_details_frame.winfo_children(): widget.destroy()
        if not self.storage_test.storage_mounts:
            self.update_status("[INFO] No testable devices found."); self.test_button.config(state="disabled"); return
        self.test_button.config(state="normal")
        ttk.Label(self.device_details_frame, text="File Transfer Test Targets (from lsblk):", font=("Helvetica", 12, "bold")).pack(anchor="w")
        for mountpoint in self.storage_test.storage_mounts: tk.Label(self.device_details_frame, text=f"  - {mountpoint}", fg="blue", font=("Helvetica", 11)).pack(anchor="w")
    def _run_and_close(self):
        t = threading.Thread(target=self._run_storage_test_and_close, daemon=True); t.start()
        self.test_button.config(state="disabled"); self.start_button.config(state="disabled")
    def _run_storage_test_and_close(self):
        self.storage_test.run_test_loop(None, duration=10)
        result = "PASS" if self.storage_test.overall_success else "FAIL"
        self.root.after(0, lambda: messagebox.showinfo("Test Summary", f"Standalone test result: {result}"))
        time.sleep(1); self.root.after(0, self.root.destroy)
    def stop_storage_test(self):
        self.storage_test.stop_test(); self.root.after(1000, self.root.destroy)
def run_standalone_test(duration):
    def cli_callback(message): print(message, flush=True)
    def progress_dummy(index, percent): pass
    tester = StorageTest(gui_callback=cli_callback)
    def signal_handler(signum, frame): print("Stop signal received, shutting down.", flush=True); tester.stop_test()
    signal.signal(signal.SIGTERM, signal_handler); signal.signal(signal.SIGINT, signal_handler)
    success = tester.run_test_loop(progress_dummy, duration)
    print(f"FINAL_RESULT:{'PASS' if success else 'FAIL'}")
    sys.exit(0)
if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1]); run_standalone_test(duration)
        except (ValueError, IndexError): print("Usage: python storage_test.py <duration_in_seconds>", file=sys.stderr); sys.exit(1)
    else:
        root = tk.Tk(); app = StorageTestApp(root); root.mainloop()
