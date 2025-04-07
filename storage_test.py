#!/usr/bin/env python3
import os
import time
import subprocess
import threading
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import re
import tkinter as tk
from tkinter import ttk, messagebox

def create_test_file(file_path, text="Sample text for USB transfer verification. " * 2):
    """
    Create a small text file (limited to 100 characters) for test purposes.
    """
    try:
        with open(file_path, 'w') as f:
            f.write(text[:100])
    except Exception as e:
        print(f"[ERROR] Failed to create test file: {e}")

def calculate_hash(file_path):
    """
    Calculate the MD5 hash of a file.
    """
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        print(f"[ERROR] Failed to calculate hash for {file_path}: {e}")
        return None

class StorageTest:
    def __init__(self, gui_callback=None):
        """
        Initialize StorageTest.
        gui_callback: Optional callback for status/progress updates.
        """
        self.stop_event = threading.Event()
        self.gui_callback = gui_callback
        self.usb_devices = []      # List of USB device strings (from lsusb)
        self.storage_devices = []  # List of storage device mountpoints (from lsblk)
        self.device_error_reported = {}  # For each device, to avoid repeated error messages

        # Dictionary to store test results.
        # Format: {"storage": [(mountpoint, success, fail)], "non_storage": [(device_info, success, fail, usb_version)]}
        self.test_results = {"storage": [], "non_storage": []}

    def _update_status(self, message):
        if self.gui_callback:
            self.gui_callback(message)
        else:
            print(message)

    def detect_usb_devices(self):
        """
        Detect USB devices using lsusb and storage devices (mountpoints) using lsblk.
        """
        self.usb_devices = []
        self.storage_devices = []
        try:
            result = subprocess.run(["lsusb"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    self.usb_devices.append(line)
            self._update_status(f"[INFO] Detected USB devices: {self.usb_devices}")
        except Exception as e:
            self._update_status(f"[ERROR] lsusb failed: {e}")
        
        try:
            lsblk_output = subprocess.check_output("lsblk -o NAME,MOUNTPOINT,SIZE,TYPE -J", shell=True).decode('utf-8')
            data = json.loads(lsblk_output)
            for dev in data.get("blockdevices", []):
                if dev.get("children"):
                    for part in dev["children"]:
                        mp = part.get("mountpoint")
                        if mp and mp.startswith("/media/"):
                            self.storage_devices.append(mp)
                            self._update_status(f"[DEBUG] Detected storage device at mountpoint: {mp}")
            if not self.storage_devices:
                lsblk_text = subprocess.check_output("lsblk -o NAME,MOUNTPOINT,SIZE,TYPE", shell=True).decode('utf-8')
                for line in lsblk_text.splitlines():
                    if '/media/' in line and 'part' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            mp = parts[1]
                            self.storage_devices.append(mp)
                            self._update_status(f"[DEBUG] Detected storage device at mountpoint: {mp}")
        except Exception as e:
            self._update_status(f"[ERROR] lsblk failed: {e}")

    def run_storage_test(self, progress_callback, duration=300):
        """
        Run tests on all detected USB devices.
        For each device:
          - If a storage device (mountpoint) is found in its info, perform a data transfer test.
          - Otherwise, perform a response test (simulate communication check and extract USB version).
        Calls progress_callback(index, percent) for progress updates.
        At the end, outputs a summary via _update_status.
        """
        self._update_status("[INFO] Starting storage test...")
        source_file = "/tmp/test_file.txt"
        create_test_file(source_file)
        self.test_results = {"storage": [], "non_storage": []}
        self.device_error_reported = {}

        with ThreadPoolExecutor() as executor:
            futures = []
            for idx, mountpoint in enumerate(self.storage_devices):
                futures.append(executor.submit(
                    self.perform_storage_test, idx, mountpoint, source_file, progress_callback, duration))
            for idx, device_info in enumerate(self.usb_devices):
                # 単純な方法：もしストレージデバイスが1件なら、最初のUSBデバイスをストレージとして扱う
                if self.storage_devices and idx == 0:
                    continue  # 既にストレージテストは行われるので除外
                else:
                    futures.append(executor.submit(
                        self.perform_non_storage_response_test, idx, device_info, progress_callback, duration))
            for future in futures:
                future.result()
        try:
            os.remove(source_file)
        except Exception as e:
            self._update_status(f"[ERROR] Failed to remove test file: {e}")
        
        summary = "[SUMMARY] Storage Test Results:\n"
        if self.test_results["storage"]:
            summary += "Storage Devices:\n"
            for mp, succ, fail in self.test_results["storage"]:
                summary += f"  Mountpoint {mp}: {succ} successes, {fail} failures.\n"
        else:
            summary += "No storage devices tested.\n"
        if self.test_results["non_storage"]:
            summary += "Non-Storage USB Devices:\n"
            for info, succ, fail, usb_version in self.test_results["non_storage"]:
                summary += f"  Device Info: {info}\n    Success: {succ}, Failures: {fail}\n    USB Version: {usb_version}\n"
        else:
            summary += "No non-storage devices tested.\n"
        self._update_status(summary)
        return summary

    def perform_storage_test(self, index, mountpoint, source_file, progress_callback, duration=300):
        """
        For a storage device: repeatedly copy the test file, verify its hash, then remove it.
        If a permission error occurs, display error and exit the loop.
        Records results in self.test_results["storage"].
        """
        target_file = os.path.join(mountpoint, "test_copy.txt")
        success_count = 0
        fail_count = 0
        start_time = time.time()
        while time.time() - start_time < duration:
            if self.stop_event.is_set():
                break
            try:
                subprocess.check_call(f"cp {source_file} {target_file}", shell=True)
                source_hash = calculate_hash(source_file)
                target_hash = calculate_hash(target_file)
                if source_hash and target_hash and source_hash == target_hash:
                    success_count += 1
                else:
                    fail_count += 1
                os.remove(target_file)
            except Exception as e:
                fail_count += 1
                if "Permission denied" in str(e):
                    self._update_status(f"[ERROR] Storage test on {mountpoint} failed: Permission denied. Ensure the device is formatted with proper user permissions.")
                    break
                else:
                    self._update_status(f"[ERROR] Storage test failed on device {index+1}: {e}")
            progress = (time.time() - start_time) / duration * 100
            progress_callback(index, progress)
            time.sleep(1)
        self.test_results["storage"].append((mountpoint, success_count, fail_count))
        self._update_status(f"[INFO] Storage test on {mountpoint} completed: {success_count} successes, {fail_count} failures.")

    def perform_non_storage_response_test(self, index, device_info, progress_callback, duration=300):
        """
        For non-storage USB devices: perform a response test by simulating a 50ms delay.
        Also, attempt to retrieve USB version info from lsusb output.
        Records results in self.test_results["non_storage"].
        """
        start_time = time.time()
        success_count = 0
        fail_count = 0
        usb_version = "Unknown"
        try:
            device_id = device_info.split()[5]  # e.g., "0930:6544"
            cmd = f"lsusb -v -d {device_id}"
            output = subprocess.check_output(cmd, shell=True).decode('utf-8')
            m = re.search(r"bcdUSB\s+([\d\.]+)", output)
            if m:
                usb_version = m.group(1)
            else:
                usb_version = "Not found"
        except Exception as e:
            usb_version = f"Error: {e}"
            if device_id not in self.device_error_reported:
                self._update_status(f"[WARN] Failed to retrieve USB info for device: {device_info}. {e}")
                self.device_error_reported[device_id] = True
        while time.time() - start_time < duration:
            if self.stop_event.is_set():
                break
            try:
                time.sleep(0.05)
                success_count += 1
            except Exception as e:
                fail_count += 1
                self._update_status(f"[ERROR] Response test failed for device {index+1}: {e}")
            progress = (time.time() - start_time) / duration * 100
            progress_callback(index, progress)
            time.sleep(1)
        self.test_results["non_storage"].append((device_info, success_count, fail_count, usb_version))
        result_msg = (f"[INFO] Response test for device {index+1} completed:\n"
                      f"Device Info: {device_info}\nSuccess: {success_count}, Failures: {fail_count}\n"
                      f"USB Version: {usb_version}")
        self._update_status(result_msg)

    def stop_test(self):
        """
        Signal to stop all running tests.
        """
        self.stop_event.set()
        self._update_status("[INFO] Storage test stopped.")

# Optional GUI for storage test (standalone usage)
class StorageTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Storage Test")
        self.root.geometry("800x600")
        self.storage_test = StorageTest(gui_callback=self.update_status)
        self.device_details_frame = tk.Frame(root)
        self.device_details_frame.pack(padx=10, pady=10)
        self.controls_frame = tk.Frame(root)
        self.controls_frame.pack(pady=10)
        self.start_button = ttk.Button(self.controls_frame, text="Detect USB Devices", command=self.display_device_status)
        self.start_button.grid(row=0, column=0, padx=10)
        self.test_button = ttk.Button(self.controls_frame, text="Start Storage Test", command=self._run_and_close)
        self.test_button.grid(row=0, column=1, padx=10)
        self.stop_button = ttk.Button(self.controls_frame, text="Stop Storage Test", command=self.stop_storage_test)
        self.stop_button.grid(row=0, column=2, padx=10)
        self.status_area = tk.Text(root, height=10, width=80, font=("Helvetica", 10))
        self.status_area.pack(pady=10)
        self.progress_bars = []

    def update_status(self, message):
        self.status_area.insert(tk.END, message + "\n")
        self.status_area.see(tk.END)

    def display_device_status(self):
        self.storage_test.detect_usb_devices()
        for widget in self.device_details_frame.winfo_children():
            widget.destroy()
        self.progress_bars = []
        # シンプルに、もしストレージデバイスがあるなら、最初のUSBデバイスをストレージとして扱う
        for index, device_info in enumerate(self.storage_test.usb_devices, start=1):
            is_storage = False
            if self.storage_test.storage_devices and index == 1:
                is_storage = True
            label_text = f"USB Device {index}: {device_info}"
            label_color = "blue" if is_storage else "green"  # Storage: blue, non-storage: green
            label = tk.Label(self.device_details_frame, text=label_text, fg=label_color, font=("Helvetica", 12))
            label.pack(anchor="w")
            progress_label = tk.Label(self.device_details_frame, text=f"Progress for USB Device {index}", fg="green", font=("Helvetica", 10))
            progress_label.pack(anchor="w")
            progress_bar = ttk.Progressbar(self.device_details_frame, orient="horizontal", length=300, mode="determinate")
            progress_bar.pack(pady=5)
            progress_bar["value"] = 0
            if is_storage:
                style = ttk.Style()
                style_name = f"Blue.Horizontal.TProgressbar{index}"
                style.configure(style_name, troughcolor='blue', background='blue')
                progress_bar.configure(style=style_name)
            self.progress_bars.append(progress_bar)
        new_height = 200 + len(self.storage_test.usb_devices) * 70
        self.root.geometry(f"800x{new_height}")

    def _run_and_close(self):
        # Run storage test in a separate thread, then display summary and close window.
        t = threading.Thread(target=self._run_storage_test_and_close, daemon=True)
        t.start()

    def _run_storage_test_and_close(self):
        summary = self.storage_test.run_storage_test(self.update_progress_bar, duration=300)
        messagebox.showinfo("Storage Test Summary", summary)
        time.sleep(1)
        self.root.destroy()

    def stop_storage_test(self):
        self.storage_test.stop_test()
        self.root.after(1000, self.root.destroy)

    def update_progress_bar(self, index, value):
        if index < len(self.progress_bars):
            self.progress_bars[index]["value"] = value

if __name__ == "__main__":
    root = tk.Tk()
    app = StorageTestApp(root)
    root.mainloop()
