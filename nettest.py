#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

CONFIG_FILENAME = "nettest_config.json"

def load_config():
    """Load network test settings from CONFIG_FILENAME.
    If file does not exist, return default settings."""
    default_config = {
        "network_type": "Wired",  # "Wired" or "Wireless"
        "target_ip": "8.8.8.8",
        "ssid": "",
        "encryption": "WPA2",
        "password": "",
        "ping_count": 4,
        "timeout": 2,
        "interval": 5
    }
    if os.path.exists(CONFIG_FILENAME):
        try:
            with open(CONFIG_FILENAME, "r") as f:
                config = json.load(f)
            return config
        except Exception as e:
            print(f"[ERROR] Failed to load config: {e}")
            return default_config
    else:
        return default_config

def save_config(config):
    """Save network test settings to CONFIG_FILENAME."""
    try:
        with open(CONFIG_FILENAME, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to save config: {e}")

def run_ping_test(target_ip, count=4, timeout=2):
    """
    Run a ping test to target_ip and return a dictionary with results.
    (Linux用の例。必要に応じてオプションを調整してください。)
    """
    try:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), target_ip]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        result = {}
        for line in output.splitlines():
            if "packets transmitted" in line:
                parts = line.split(",")
                result["transmitted"] = int(parts[0].split()[0])
                result["received"] = int(parts[1].split()[0])
                result["packet_loss"] = float(parts[2].strip().split("%")[0])
            if "rtt min/avg/max/mdev" in line:
                rtt_values = line.split("=")[1].split()[0].split("/")
                result["min_rtt"] = float(rtt_values[0])
                result["avg_rtt"] = float(rtt_values[1])
                result["max_rtt"] = float(rtt_values[2])
        return result
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.output}

def run_network_test_loop(stop_event, target_ip, test_interval, callback):
    """
    連続して ping テストを実行するループ。
    stop_event がセットされるまで、指定の間隔で ping を実行し、結果を callback(result) で返す。
    """
    while not stop_event.is_set():
        result = run_ping_test(target_ip, count=4, timeout=2)
        callback(result)
        for _ in range(test_interval):
            if stop_event.is_set():
                break
            time.sleep(1)

class NetworkTestApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()  # 設定ファイルの読み込み

        self.root.title("Network Test Settings")
        self.root.geometry("400x450")

        # ネットワーク種別
        self.network_type = tk.StringVar(value=self.config.get("network_type", "Wired"))
        self.target_ip = tk.StringVar(value=self.config.get("target_ip", "8.8.8.8"))
        self.ssid = tk.StringVar(value=self.config.get("ssid", ""))
        self.encryption = tk.StringVar(value=self.config.get("encryption", "WPA2"))
        self.password = tk.StringVar(value=self.config.get("password", ""))
        self.ping_count = tk.IntVar(value=self.config.get("ping_count", 4))
        self.timeout = tk.IntVar(value=self.config.get("timeout", 2))
        self.interval = tk.IntVar(value=self.config.get("interval", 5))

        # ネットワークテストの連続実行用の停止イベントとスレッド
        self.stop_event = threading.Event()
        self.test_thread = None

        # UI の作成
        frame = ttk.Frame(root)
        frame.pack(padx=10, pady=10, fill="x")

        ttk.Label(frame, text="Select Network Type:").pack(anchor="w")
        ttk.Radiobutton(frame, text="Wired", variable=self.network_type, value="Wired", command=self.update_fields).pack(anchor="w")
        ttk.Radiobutton(frame, text="Wireless", variable=self.network_type, value="Wireless", command=self.update_fields).pack(anchor="w")

        # Wired: ターゲットIP
        ttk.Label(frame, text="Target IP:").pack(anchor="w", pady=(10,0))
        self.ip_entry = ttk.Entry(frame, textvariable=self.target_ip)
        self.ip_entry.pack(anchor="w", fill="x")

        # Wireless用設定（初期は非表示）
        self.wireless_frame = ttk.Frame(frame)
        self.ssid_label = ttk.Label(self.wireless_frame, text="SSID:")
        self.ssid_entry = ttk.Entry(self.wireless_frame, textvariable=self.ssid)
        self.enc_label = ttk.Label(self.wireless_frame, text="Encryption:")
        self.enc_entry = ttk.Entry(self.wireless_frame, textvariable=self.encryption)
        self.pwd_label = ttk.Label(self.wireless_frame, text="Password:")
        self.pwd_entry = ttk.Entry(self.wireless_frame, textvariable=self.password, show="*")
        self.ssid_label.pack(anchor="w")
        self.ssid_entry.pack(anchor="w", fill="x")
        self.enc_label.pack(anchor="w")
        self.enc_entry.pack(anchor="w", fill="x")
        self.pwd_label.pack(anchor="w")
        self.pwd_entry.pack(anchor="w", fill="x")
        self.wireless_frame.pack_forget()

        # Ping設定
        ttk.Label(frame, text="Ping Count:").pack(anchor="w", pady=(10,0))
        self.ping_count_entry = ttk.Entry(frame, textvariable=self.ping_count)
        self.ping_count_entry.pack(anchor="w", fill="x")
        ttk.Label(frame, text="Timeout (sec):").pack(anchor="w", pady=(5,0))
        self.timeout_entry = ttk.Entry(frame, textvariable=self.timeout)
        self.timeout_entry.pack(anchor="w", fill="x")
        ttk.Label(frame, text="Interval (sec):").pack(anchor="w", pady=(5,0))
        self.interval_entry = ttk.Entry(frame, textvariable=self.interval)
        self.interval_entry.pack(anchor="w", fill="x")

        # 設定保存ボタン
        ttk.Button(frame, text="Save Settings", command=self.save_settings).pack(pady=(10,0))
        # 連続テスト開始ボタン
        ttk.Button(frame, text="Start Continuous Test", command=self.start_test).pack(pady=(10,0))
        # 中断ボタン
        ttk.Button(frame, text="Stop Test", command=self.stop_test).pack(pady=(5,10))

        # 結果表示エリア
        self.result_area = tk.Text(root, height=8, width=50, font=("Helvetica", 10))
        self.result_area.pack(padx=10, pady=10)

        self.update_fields()

    def update_fields(self):
        if self.network_type.get() == "Wireless":
            self.wireless_frame.pack(fill="x", pady=(10,0))
        else:
            self.wireless_frame.pack_forget()

    def save_settings(self):
        config = {
            "network_type": self.network_type.get(),
            "target_ip": self.target_ip.get(),
            "ssid": self.ssid.get(),
            "encryption": self.encryption.get(),
            "password": self.password.get(),
            "ping_count": self.ping_count.get(),
            "timeout": self.timeout.get(),
            "interval": self.interval.get()
        }
        save_config(config)
        messagebox.showinfo("Network Test", "Settings saved successfully.")

    def start_test(self):
        target = self.target_ip.get()
        if not target:
            messagebox.showerror("Error", "Target IP is required.")
            return
        self.result_area.delete("1.0", tk.END)
        self.stop_event.clear()
        # スレッドで連続テストを開始
        self.test_thread = threading.Thread(target=self.network_test_loop, args=(target,), daemon=True)
        self.test_thread.start()

    def network_test_loop(self, target):
        count = self.ping_count.get()
        timeout = self.timeout.get()
        interval = self.interval.get()
        while not self.stop_event.is_set():
            result = run_ping_test(target, count=count, timeout=timeout)
            self.result_area.insert(tk.END, f"Ping Test Result for {target}:\n{result}\n")
            self.result_area.see(tk.END)
            for _ in range(interval):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

    def stop_test(self):
        self.stop_event.set()
        messagebox.showinfo("Network Test", "Network test stopped.")

if __name__ == "__main__":
    root = tk.Tk()
    app = NetworkTestApp(root)
    root.mainloop()
