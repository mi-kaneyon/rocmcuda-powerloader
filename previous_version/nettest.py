import os
import subprocess
import json
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time

MODULE_DIR      = os.path.dirname(__file__)
CONFIG_FILENAME = os.path.join(MODULE_DIR, "nettest_config.json")


def detect_default_gateway():
    """`ip route` からデフォルトゲートウェイをパースして返す。失敗時は None."""
    try:
        out = subprocess.check_output(["ip", "route"], universal_newlines=True)
        for line in out.splitlines():
            if line.startswith("default via"):
                return line.split()[2]
    except Exception:
        pass
    return None


def ensure_config():
    """設定ファイルが存在しない場合、デフォルト値で作成する。"""
    if not os.path.exists(CONFIG_FILENAME):
        default_cfg = {
            "network_type": "Wired",
            "target_ip":    detect_default_gateway() or "8.8.8.8",
            "ping_count":   4,
            "timeout":      2,
            "interval":     5
        }
        save_config(default_cfg)
    return load_config()


def load_config():
    try:
        with open(CONFIG_FILENAME, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG_FILENAME, "w") as f:
        json.dump(cfg, f, indent=4)


def run_ping_test(target_ip, count=4, timeout=2):
    """ping を実行して辞書で結果を返す。"""
    try:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), target_ip]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        res = {}
        for L in out.splitlines():
            if "packets transmitted" in L:
                p = L.split(",")
                res["tx"]   = int(p[0].split()[0])
                res["rx"]   = int(p[1].split()[0])
                res["loss"] = float(p[2].split("%")[0])
            if "rtt min/avg/max/mdev" in L:
                a = L.split("=")[1].split()[0].split("/")
                res["min"], res["avg"], res["max"] = map(float, a[:3])
        return res
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "output": e.output}


def run_network_test_loop(stop_event, callback):
    """
    stop_event がセットされるまで以下を繰り返す：
      1) 設定ファイルを読んで target_ip を取得
      2) target_ip がデフォルト(8.8.8.8)ならゲートウェイを再検出
      3) ping を実行して結果を callback に渡す
      4) interval 秒だけ待つ
    """
    while not stop_event.is_set():
        cfg = ensure_config()
        tgt = cfg.get("target_ip", "8.8.8.8")
        if tgt == "8.8.8.8":
            gw = detect_default_gateway()
            if gw:
                tgt = gw
        res = run_ping_test(
            tgt,
            count=cfg.get("ping_count", 4),
            timeout=cfg.get("timeout", 2)
        )
        callback(tgt, res)
        for _ in range(cfg.get("interval", 5)):
            if stop_event.is_set():
                break
            time.sleep(1)


class NetworkTestApp:
    def __init__(self, root):
        self.root = root
        self.stop_event = threading.Event()
        self.cfg = ensure_config()

        root.title("Network Test Settings")
        root.geometry("400x500")

        # メインフレーム
        frame = ttk.Frame(root)
        frame.pack(padx=10, pady=10, fill="x")

        # 設定画面ラベル
        ttk.Label(frame, text="Network Test Configuration", font=(None, 14)).pack(pady=5)

        # network_type
        ttk.Label(frame, text="Network Type:").pack(anchor="w")
        self.network_type = tk.StringVar(value=self.cfg.get("network_type", "Wired"))
        ttk.Combobox(frame, textvariable=self.network_type,
                     values=["Wired", "Wireless"]).pack(fill="x")

        # target_ip
        ttk.Label(frame, text="Target IP:").pack(anchor="w", pady=(10,0))
        self.target_ip = tk.StringVar(value=self.cfg.get("target_ip", ""))
        ttk.Entry(frame, textvariable=self.target_ip).pack(fill="x")

        # ping_count
        ttk.Label(frame, text="Ping Count:").pack(anchor="w", pady=(10,0))
        self.ping_count = tk.IntVar(value=self.cfg.get("ping_count", 4))
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self.ping_count).pack(fill="x")

        # timeout
        ttk.Label(frame, text="Timeout (s):").pack(anchor="w", pady=(10,0))
        self.timeout = tk.IntVar(value=self.cfg.get("timeout", 2))
        ttk.Spinbox(frame, from_=1, to=60, textvariable=self.timeout).pack(fill="x")

        # interval
        ttk.Label(frame, text="Interval (s):").pack(anchor="w", pady=(10,0))
        self.interval = tk.IntVar(value=self.cfg.get("interval", 5))
        ttk.Spinbox(frame, from_=1, to=3600, textvariable=self.interval).pack(fill="x")

        # ボタン
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=15, fill="x")
        ttk.Button(btn_frame, text="Save Settings", command=self.save).pack(side="left", expand=True)
        ttk.Button(btn_frame, text="Start Test",   command=self.start).pack(side="left", expand=True)
        ttk.Button(btn_frame, text="Stop Test",    command=self.stop).pack(side="left", expand=True)

        # 結果エリア
        self.result_area = tk.Text(root, height=10)
        self.result_area.pack(padx=10, pady=(0,10), fill="both", expand=True)

    def save(self):
        cfg = {
            "network_type": self.network_type.get(),
            "target_ip":    self.target_ip.get(),
            "ping_count":   self.ping_count.get(),
            "timeout":      self.timeout.get(),
            "interval":     self.interval.get()
        }
        save_config(cfg)
        messagebox.showinfo("Network Test", "Settings saved.")

    def start(self):
        self.result_area.delete("1.0", tk.END)
        self.stop_event.clear()
        threading.Thread(
            target=run_network_test_loop,
            args=(self.stop_event, self._on_result),
            daemon=True
        ).start()

    def _on_result(self, target, result):
        self.result_area.insert(tk.END, f"→ {target}: {result}\n")
        self.result_area.see(tk.END)

    def stop(self):
        self.stop_event.set()
        messagebox.showinfo("Network Test", "Test stopped.")


if __name__ == "__main__":
    root = tk.Tk()
    app = NetworkTestApp(root)
    root.mainloop()
