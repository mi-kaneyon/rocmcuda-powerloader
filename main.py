#!/usr/bin/env python3
import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import multiprocessing
import time
import psutil
import torch



# --- util モジュール ---
from util.test_runner import (
    run_cpu_load,
    run_gpu_load,
    run_storage_test,
    run_network_test,
    run_sound_test
)
from util.test_manager   import stop_all_tests
from util.result_manager import show_summary_window
from util.ui_helpers     import create_burnin_popup, create_net_popup
# --- 個別テストモジュール ---
from storage_load.storage_test import StorageTestApp
from network_test.nettest import NetworkTestApp


try:
    from cpu_load.cpu_load import apply_cpu_load, apply_cpu_load_x86
except ImportError:
    apply_cpu_load, apply_cpu_load_x86 = None, None
    print("Warning: cpu_load module not found. CPU tests will be skipped.")

try:
    from gpu_load.gpu_load import apply_gpu_tensor_load, apply_combined_load, apply_gpu_vram_load
except ImportError:
    apply_gpu_tensor_load, apply_combined_load, apply_gpu_vram_load = None, None, None
    print("Warning: gpu_load module not found. GPU tests will be skipped.")

try:
    from system_info.system_info import get_cpu_info, get_gpu_info, get_psu_power
except ImportError:
    get_cpu_info = lambda: "CPU info module not found."
    get_gpu_info = lambda: "GPU info module not found."
    get_psu_power = lambda: "PSU Power: N/A (module not found)"
    print("Warning: system_info module not found.")

try:
    from storage_load.storage_test import StorageTest, StorageTestApp
except ImportError:
    StorageTest, StorageTestApp = None, None
    print("Warning: storage_test module not found. Storage test will be skipped.")

try:
    from network_test.nettest import NetworkTestApp, run_network_test_loop
except ImportError:
    NetworkTestApp, run_network_test_loop = None, None
    print("Warning: nettest module not found. Network test will be skipped.")

try:
    from sound_test.noisetester import play_and_record_main
except ImportError:
    play_and_record_main = None
    print("Warning: noisetester module not found. Sound test will be skipped.")

# --- グローバル変数 ---
start_event = threading.Event()

# --- テスト実行ラッパー関数 ---

def run_cpu_load_wrapper(cpu_func, cpu_load_percentage, stop_event):
    start_event.wait()
    if cpu_func:
        cpu_func(cpu_load_percentage, stop_event)

def run_gpu_load_wrapper(gpu_func, gpu_load_percentage, gpu_ids, stop_event):
    start_event.wait()
    if gpu_func:
        gpu_func(gpu_load_percentage, stop_event, gpu_ids)

def run_sound_test_wrapper(app, stop_event, info_area, sound_threshold, duration):
    start_event.wait()
    time.sleep(3)  # マイクの準備時間

    if play_and_record_main is None:
        app.root.after(0, lambda: info_area.insert(tk.END, "[Sound Loop] Sound test module not found.\n"))
        app.test_results["Sound"] = "SKIP"
        return

    results = []
    end_time = time.time() + duration
    app.test_results["Sound"] = "FAIL"

    while time.time() < end_time and not stop_event.is_set():
        try:
            mean_corr = play_and_record_main()
            results.append(mean_corr)
            app.root.after(0, lambda mc=mean_corr: info_area.insert(tk.END, f"[Sound Loop] Mean correlation: {mc:.4f}\n"))
        except Exception as e:
            app.root.after(0, lambda err=e: info_area.insert(tk.END, f"[Sound Loop] Exception: {err}\n"))
            return

        if stop_event.wait(timeout=3):
            break

    if not results:
        app.test_results["Sound"] = "SKIP"
    elif any(r >= sound_threshold for r in results):
        app.test_results["Sound"] = "PASS"

def run_storage_test_wrapper(app, storage_instance, progress_callback, stop_event, duration):
    """
    [修正] StorageTestクラスのメソッド呼び出しを修正し、結果判定を確実に行う。
    """
    start_event.wait()
    if stop_event.is_set():
        app.test_results["Storage"] = "SKIP"
        return

    app.test_results["Storage"] = "FAIL"  # デフォルトはFAIL

    def monitor_stop():
        stop_event.wait()
        if storage_instance:
            storage_instance.stop_test()
            app.root.after(0, lambda: app.update_status("[Storage Test] Stop signal received, attempting to halt."))

    monitor_thread = threading.Thread(target=monitor_stop, daemon=True)
    monitor_thread.start()

    try:
        # run_storage_test -> run_test_loop に修正し、戻り値を受け取る
        success = storage_instance.run_test_loop(progress_callback, duration)
        if not stop_event.is_set():
            # テストが完走した場合、run_test_loopの結果に基づいて判定
            app.test_results["Storage"] = "PASS" if success else "FAIL"
        else:
            # 手動で停止された場合はSKIP
            app.test_results["Storage"] = "SKIP"
    except Exception as e:
        app.test_results["Storage"] = "FAIL"
        app.root.after(0, lambda e=e: app.update_status(f"[Storage Test] Exception: {e}"))

def run_network_test_wrapper(app, stop_event, net_area, duration):
    """
    [修正] ネットワークテストのラッパー関数を整理。
    不要なコードを削除し、指定時間テストを実行して結果を判定するロジックを確実にする。
    """
    if run_network_test_loop is None:
        app.root.after(0, lambda: net_area.insert(tk.END, "[Network Test] Module not found.\n"))
        app.test_results["Network"] = "SKIP"
        return

    start_event.wait()
    if stop_event.is_set():
        app.test_results["Network"] = "SKIP"
        return

    app.test_results["Network"] = "FAIL"  # デフォルトはFAIL
    any_success = False
    any_failure = False

    def callback(target, result):
        nonlocal any_success, any_failure
        if isinstance(result, dict):
            if "error" in result:
                res_str = f"FAIL ({result.get('error')})"
                any_failure = True
            elif result.get("loss", 100.0) > 0:
                res_str = f"FAIL (Loss: {result.get('loss')}%)"
                any_failure = True
            else:
                res_str = f"SUCCESS (avg: {result.get('avg', 'N/A')}ms)"
                any_success = True
        else:
            res_str = str(result)
            if "fail" in res_str.lower() or "error" in res_str.lower():
                any_failure = True
            else:
                any_success = True

        app.root.after(0, lambda t=target, r=res_str: net_area.insert(tk.END, f"→ {t}: {r}\n"))
        app.root.after(0, net_area.see, tk.END)

    network_thread = threading.Thread(
        target=run_network_test_loop,
        args=(stop_event, callback),
        daemon=True
    )
    network_thread.start()

    # 指定時間待機するか、手動で停止されるのを待つ
    stop_event.wait(timeout=duration)

    # 時間経過または手動停止後、テストループを確実に停止させる
    if not stop_event.is_set():
        stop_event.set()

    # ネットワークスレッドが終了するのを少し待つ
    network_thread.join(timeout=5)

    # 最終判定
    if any_success and not any_failure:
        app.test_results["Network"] = "PASS"
    elif not any_success and not any_failure:
        app.test_results["Network"] = "SKIP"
    # それ以外（any_failure is True）の場合は、デフォルトのFAILのまま

def create_burnin_popup(root):
    popup = tk.Toplevel(root)
    popup.title("Burn‑in Test Progress")
    popup.geometry("600x400")
    progress_area = tk.Text(popup, height=20, width=70, font=("Helvetica", 10))
    progress_area.pack(padx=10, pady=10)
    return popup, progress_area

def create_net_popup(root):
    popup = tk.Toplevel(root)
    popup.title("Network Test Progress")
    popup.geometry("400x300")
    net_area = tk.Text(popup, height=15, width=50, font=("Helvetica", 10))
    net_area.pack(padx=10, pady=10)
    return popup, net_area

# --- メインアプリケーションクラス ---

class LoadTestApp:
    def __init__(self, root):
        self.root = root
        self.root.title("System Power Loading Tester")
        self.root.geometry("1200x900")

        self.burn_in_active = False
        self.summary_window = None
        self.sound_threshold = 0.6
        self.update_loop_id = None

        self.cpu_load = tk.IntVar(value=0)
        self.gpu_load = tk.IntVar(value=0)
        self.gpu_vram_load = tk.IntVar(value=0)
        self.gpu_load_type = tk.StringVar(value="3D Render")
        self.cpu_load_type = tk.StringVar(value="Standard")

        self.cpu_stop_event     = None
        self.gpu_stop_event     = None
        self.storage_stop_event = None
        self.sound_stop_event   = None
        self.network_stop_event = None
        self.burnin_stop_event  = threading.Event()

        self.burnin_duration = tk.IntVar(value=50)
        self.stress_level = tk.StringVar(value="Low")

        self.stop_event = None
        self.burnin_stop_event = threading.Event()
        self.cpu_threads = []
        self.cpu_processes = []
        self.gpu_threads = []
        self.sound_test_thread = None
        self.storage_test_thread = None
        self.network_test_thread = None
        self.net_popup = None
        self.burnin_popup = None

        self.test_results = {
            "CPU": "SKIP", "GPU": "SKIP", "VRAM": "SKIP",
            "Storage": "SKIP", "Sound": "SKIP", "Network": "SKIP"
        }

        self._setup_ui()
        self.display_system_info()

    def _setup_ui(self):
        controls_frame = tk.Frame(self.root)
        controls_frame.grid(column=0, row=0, padx=10, pady=10)
        ttk.Label(controls_frame, text="CPU Load (%)").grid(column=0, row=0, padx=10, pady=5)
        self.cpu_slider = ttk.Scale(controls_frame, from_=0, to=100, variable=self.cpu_load)
        self.cpu_slider.grid(column=1, row=0, padx=10, pady=5)
        ttk.Label(controls_frame, text="CPU Load Type").grid(column=0, row=1, padx=10, pady=5)
        self.cpu_load_standard = ttk.Radiobutton(controls_frame, text="Standard", variable=self.cpu_load_type, value="Standard")
        self.cpu_load_standard.grid(column=1, row=1, padx=10, pady=5)
        self.cpu_load_x86 = ttk.Radiobutton(controls_frame, text="x86 Instructions", variable=self.cpu_load_type, value="x86")
        self.cpu_load_x86.grid(column=2, row=1, padx=10, pady=5)
        ttk.Label(controls_frame, text="GPU Load (%)").grid(column=0, row=2, padx=10, pady=5)
        self.gpu_slider = ttk.Scale(controls_frame, from_=0, to=100, variable=self.gpu_load)
        self.gpu_slider.grid(column=1, row=2, padx=10, pady=5)
        ttk.Label(controls_frame, text="GPU VRAM Load (%)").grid(column=0, row=3, padx=10, pady=5)
        self.gpu_vram_slider = ttk.Scale(controls_frame, from_=0, to=100, variable=self.gpu_vram_load)
        self.gpu_vram_slider.grid(column=1, row=3, padx=10, pady=5)
        ttk.Label(controls_frame, text="GPU Load Type").grid(column=0, row=4, padx=10, pady=5)
        self.gpu_load_3d = ttk.Radiobutton(controls_frame, text="3D Render", variable=self.gpu_load_type, value="3D Render")
        self.gpu_load_3d.grid(column=1, row=4, padx=10, pady=5)
        self.gpu_load_tensor = ttk.Radiobutton(controls_frame, text="Model Training", variable=self.gpu_load_type, value="Model Training")
        self.gpu_load_tensor.grid(column=2, row=4, padx=10, pady=5)
        self.start_button = ttk.Button(controls_frame, text="Start Load", command=self.apply_load)
        self.start_button.grid(column=0, row=5, padx=10, pady=10)
        self.stop_button = ttk.Button(controls_frame, text="Stop Load", command=self.stop_all_tests)
        self.stop_button.grid(column=1, row=5, padx=10, pady=10)
        self.storage_test_button = ttk.Button(controls_frame, text="Storage Test", command=self.open_storage_window)
        self.storage_test_button.grid(column=2, row=5, padx=10, pady=10)
        self.sound_test_button = ttk.Button(controls_frame, text="Sound Test", command=self.open_sound_test_window)
        self.sound_test_button.grid(column=3, row=5, padx=10, pady=10)
        self.network_test_button = ttk.Button(controls_frame, text="Network Test", command=self.open_network_test_window)
        self.network_test_button.grid(column=4, row=5, padx=10, pady=10)
        self.exit_button = ttk.Button(controls_frame, text="Exit", command=self.exit_app)
        self.exit_button.grid(column=5, row=5, padx=10, pady=10)
        ttk.Separator(controls_frame, orient="horizontal").grid(column=0, row=6, columnspan=6, sticky="ew", pady=10)
        ttk.Label(controls_frame, text="Burn‑in Test Duration (sec):").grid(column=0, row=7, padx=10, pady=5)
        self.burnin_entry = ttk.Entry(controls_frame, textvariable=self.burnin_duration, width=10)
        self.burnin_entry.grid(column=1, row=7, padx=10, pady=5)
        ttk.Label(controls_frame, text="Stress Level:").grid(column=2, row=7, padx=10, pady=5)
        self.stress_combo = ttk.Combobox(controls_frame, textvariable=self.stress_level, values=["Low", "Mid", "High"], state="readonly", width=10)
        self.stress_combo.grid(column=3, row=7, padx=10, pady=5)
        self.stress_combo.set("Low")
        self.burnin_button = ttk.Button(controls_frame, text="Run Burn‑in Test", command=self.run_burn_in_test)
        self.burnin_button.grid(column=4, row=7, padx=10, pady=5)
        self.info_area = tk.Text(self.root, height=10, width=100, font=("Helvetica", 14))
        self.info_area.grid(column=0, row=1, columnspan=6, padx=10, pady=10)
        self.info_area.insert(tk.END, "System Information will appear here.\n")
        self.psu_power_label = tk.Label(self.root, text="PSU Power: N/A", font=("Helvetica", 14))
        self.psu_power_label.grid(column=0, row=2, columnspan=6, pady=10)
        self.cpu_usage_label = tk.Label(self.root, text="CPU Usage: N/A", font=("Helvetica", 14))
        self.cpu_usage_label.grid(column=0, row=3, columnspan=6, pady=10)
        self.memory_usage_label = tk.Label(self.root, text="Memory Usage: N/A", font=("Helvetica", 14))
        self.memory_usage_label.grid(column=0, row=4, columnspan=6, pady=10)
        self.gpu_vram_label = tk.Label(self.root, text="VRAM Usage: N/A", font=("Helvetica", 14))
        self.gpu_vram_label.grid(column=0, row=5, columnspan=6, pady=10)


    def set_ui_state(self, is_testing):
        state = 'disabled' if is_testing else 'normal'
        widgets = [
            self.start_button, self.burnin_button,
            self.cpu_slider, self.gpu_slider, self.gpu_vram_slider,
            self.cpu_load_standard, self.cpu_load_x86,
            self.gpu_load_3d, self.gpu_load_tensor,
            self.burnin_entry, self.stress_combo,
            self.storage_test_button, self.network_test_button, self.sound_test_button
        ]
        for w in widgets:
            w.config(state=state)



    def apply_load(self):
        """
        単独ロード実行時に CPU / GPU / VRAM / Storage / Network / Sound テストを
        並行して起動します。
        """
        # 1) 既存テスト停止＆UIロック
        self.stop_all_tests(lambda: None)
        self.set_ui_state(True)

        # 2) 停止イベントを上書き生成
        self.cpu_stop_event     = multiprocessing.Event() if self.cpu_load_type.get() == "x86" else threading.Event()
        self.gpu_stop_event     = threading.Event()
        self.storage_stop_event = threading.Event()
        self.network_stop_event = threading.Event()
        self.sound_stop_event   = threading.Event()

        # 3) パラメータ取得
        cpu_val  = self.cpu_load.get()
        gpu_val  = self.gpu_load.get()
        vram_val = self.gpu_vram_load.get()
        duration = self.burnin_duration.get()

        # 4) ステータス出力
        self.update_status(f"Starting tests → CPU={cpu_val}%, GPU={gpu_val}%, VRAM={vram_val}%, Duration={duration}s")

        # 5) CPU 負荷テスト
        if cpu_val > 0 and apply_cpu_load:
            t_cpu = threading.Thread(
                target=run_cpu_load,
                args=(self, cpu_val, self.cpu_stop_event),
                daemon=True
            )
            self.cpu_threads.append(t_cpu)
            t_cpu.start()

        # 6) GPU / VRAM 負荷テスト
        if torch.cuda.is_available() and (gpu_val > 0 or vram_val > 0):
            t_gpu = threading.Thread(
                target=run_gpu_load,
                args=(self, gpu_val, vram_val, self.gpu_stop_event),
                daemon=True
            )
            self.gpu_threads.append(t_gpu)
            t_gpu.start()

        # 7) Storage テスト
        t_storage = threading.Thread(
            target=run_storage_test,
            args=(self, self.storage_stop_event, duration),
            daemon=True
        )
        self.storage_test_thread = t_storage
        t_storage.start()

        # 8) Network テスト
        self.net_popup, net_area = create_net_popup(self.root)
        t_net = threading.Thread(
            target=run_network_test,
            args=(self, self.network_stop_event, net_area, duration),
            daemon=True
        )
        self.network_test_thread = t_net
        t_net.start()

        # 9) Sound テスト
        self.burnin_popup, burn_area = create_burnin_popup(self.root)
        t_sound = threading.Thread(
            target=run_sound_test,
            args=(self, self.sound_stop_event, burn_area, self.sound_threshold, duration),
            daemon=True
        )
        self.sound_test_thread = t_sound
        t_sound.start()




    # ──────────────────────────────────────────────────────

    def run_burn_in_test(self):
        """
        Burn‑in テストを CPU / GPU+VRAM / Storage / Network / Sound の５つを
        同時に走らせ、duration 秒後に一括停止してサマリを表示します。
        """
        # ① 既存のポップアップが残っていれば破棄
        for attr in ("net_popup", "burnin_popup"):
            popup = getattr(self, attr, None)
            if popup and popup.winfo_exists():
                popup.destroy()
            setattr(self, attr, None)

        # ② ストレスレベルに合わせて各負荷値を設定
        level = self.stress_level.get()
        cpu_pct, gpu_pct, vram_pct = {
            "Low":  (30, 30, 30),
            "Mid":  (60, 60, 60),
            "High": (80, 80, 80),
        }[level]
        self.cpu_load.set(cpu_pct)
        self.gpu_load.set(gpu_pct)
        self.gpu_vram_load.set(vram_pct)
        self.update_status(f"Burn‑in → CPU={cpu_pct}%, GPU={gpu_pct}%, VRAM={vram_pct}%")

        # ③ UIをロック & 停止イベントを再生成
        self.set_ui_state(True)
        duration = self.burnin_duration.get()
        self.cpu_stop_event     = threading.Event()
        self.gpu_stop_event     = threading.Event()
        self.storage_stop_event = threading.Event()
        self.network_stop_event = threading.Event()
        self.sound_stop_event   = threading.Event()

        # ④ 各テストを並行実行
        threading.Thread(
            target=run_cpu_load,
            args=(self, cpu_pct, self.cpu_stop_event),
            daemon=True
        ).start()

        threading.Thread(
            target=run_gpu_load,
            args=(self, gpu_pct, vram_pct, self.gpu_stop_event),
            daemon=True
        ).start()
        self.update_status("[GPU] burn‑in thread launched")

        threading.Thread(
            target=run_storage_test,
            args=(self, self.storage_stop_event, duration),
            daemon=True
        ).start()

        self.net_popup, net_area = create_net_popup(self.root)
        threading.Thread(
            target=run_network_test,
            args=(self, self.network_stop_event, net_area, duration),
            daemon=True
        ).start()

        self.burnin_popup, burn_area = create_burnin_popup(self.root)
        threading.Thread(
            target=run_sound_test,
            args=(self, self.sound_stop_event, burn_area, self.sound_threshold, duration),
            daemon=True
        ).start()

        # ⑤ duration 秒後に全テストを停止 → 完走時に _on_burnin_complete を呼び出し
        self.root.after(
            duration * 1000,
            lambda: self.stop_all_tests(self._on_burnin_complete)
        )





    def _on_burnin_complete(self):
        """
        duration 秒内に全テストが完走したときの処理。
        """
        # 1) すでに開いているサブウィンドウを閉じる
        for attr in ("net_popup", "burnin_popup"):
            popup = getattr(self, attr, None)
            if popup and popup.winfo_exists():
                popup.destroy()
            setattr(self, attr, None)            # ← 変数をクリア

        # 2) 総合サマリを表示
        show_summary_window(self)

        # 3) UI を戻してシステム情報をリセット
        self.set_ui_state(False)
        self.reset_system_info()







    def _burn_in_timer(self, duration):
        completed_fully = not self.burnin_stop_event.wait(timeout=duration)
        self.root.after(0, self.stop_all_tests, lambda: self._on_test_done(completed_fully))

    def _on_test_done(self, completed_fully):
        """
        [修正] テスト完了時の処理。手動停止の場合、負荷テストの結果をSKIPに変更する。
        """
        if not completed_fully:
            self.update_status("\nBurn-in Test was stopped manually.\n")
            # 手動停止の場合、完走していない負荷テストの結果をSKIPにする
            # 起動に成功した場合、結果は 'PASS' になっている
            if self.test_results["CPU"] == "PASS":
                self.test_results["CPU"] = "SKIP"
            if self.test_results["GPU"] == "PASS":
                self.test_results["GPU"] = "SKIP"
            if self.test_results["VRAM"] == "PASS":
                self.test_results["VRAM"] = "SKIP"
        else:
            self.update_status("\nBurn-in Test completed.\n")

        # 起動失敗('FAIL')や、ラッパー内で結果が確定するテスト(Storage等)はそのまま

        self.show_summary_window()
        self.burn_in_active = False
        self.set_ui_state(False)
        self.reset_system_info()

    def show_summary_window(self):
        if self.summary_window and self.summary_window.winfo_exists():
            self.summary_window.destroy()

        self.summary_window = tk.Toplevel(self.root)
        self.summary_window.title("Burn-in Test Summary")
        self.summary_window.geometry("400x300")
        self.summary_window.transient(self.root)

        frame = ttk.Frame(self.summary_window, padding="10")
        frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(frame, text="Test Results", font=("Helvetica", 16, "bold")).pack(pady=10)

        colors = {"PASS": "green", "FAIL": "red", "SKIP": "gray"}
        for test_name, result in self.test_results.items():
            result_frame = ttk.Frame(frame)
            result_frame.pack(fill=tk.X, pady=2)
            ttk.Label(result_frame, text=f"{test_name}:", width=10, anchor="w").pack(side=tk.LEFT, padx=5)
            ttk.Label(result_frame, text=result, foreground=colors.get(result, "black"), font=("Helvetica", 12, "bold")).pack(side=tk.LEFT, padx=5)

        close_button = ttk.Button(frame, text="Close", command=self.summary_window.destroy)
        close_button.pack(pady=20)
        self.summary_window.protocol("WM_DELETE_WINDOW", self.summary_window.destroy)


    def _join_all_threads(self, on_done_callback=None):
        # 既存の join／terminate ロジック …
        for th in self.cpu_threads + self.gpu_threads + [
            self.storage_test_thread,
            self.network_test_thread,
            self.sound_test_thread
        ]:
            if th and th.is_alive():
                th.join(timeout=5)
        for p in self.cpu_processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)

        # UI 再有効化
        self.root.after(0, self.set_ui_state, False)
        # 完了コールバック
        if on_done_callback:
            self.root.after(0, on_done_callback)
        else:
            self.root.after(0, lambda: self.update_status("\nAll tests stopped.\n"))


    def stop_all_tests(self, on_done_callback=None):
        """
        全テストの停止イベントをセットし、バックグラウンドで
        _join_all_threads() を呼び出します。
        on_done_callback があれば、全スレッド終了後に実行されます。
        """
        for ev in (
            self.cpu_stop_event,
            self.gpu_stop_event,
            self.storage_stop_event,
            self.network_stop_event,
            self.sound_stop_event,
        ):
            if ev:
                ev.set()
        threading.Thread(
            target=self._join_all_threads,
            args=(on_done_callback,),
            daemon=True
        ).start()

    def update_system_info(self):
        try:
            psu_power = get_psu_power()
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent

            vram_usage = 0
            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                total_mem = sum(torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count()))
                allocated_mem = sum(torch.cuda.memory_allocated(i) for i in range(torch.cuda.device_count()))
                if total_mem > 0:
                    vram_usage = (allocated_mem / total_mem) * 100

            self.psu_power_label.config(text=psu_power)
            self.cpu_usage_label.config(text=f"CPU Usage: {cpu_usage}%")
            self.memory_usage_label.config(text=f"Memory Usage: {memory_usage}%")
            self.gpu_vram_label.config(text=f"VRAM Usage: {vram_usage:.2f}%")
        except Exception as e:
            print(f"Error updating system info: {e}")
        finally:
            # Schedule next update after 2 seconds
            self.update_loop_id = self.root.after(2000, self.update_system_info)

    def start_update_loop(self):
        if self.update_loop_id:
            self.root.after_cancel(self.update_loop_id)
        psutil.cpu_percent()  # Prime the CPU percent function
        self.update_system_info()

    def exit_app(self):
        if self.burn_in_active and not messagebox.askyesno("Exit", "A burn-in test is running. Are you sure you want to exit?"):
            return
        self.stop_all_tests()
        self.root.after(200, self._final_exit)

    def _final_exit(self):
        if self.update_loop_id:
            self.root.after_cancel(self.update_loop_id)
        self.root.quit()
        self.root.destroy()
        os._exit(0)

    def update_status(self, message):
        """Append a message to the info_area log and auto-scroll."""
        if self.root.winfo_exists():
            self.root.after(0, lambda: self.info_area.insert(tk.END, message + "\n"))
            self.root.after(0, lambda: self.info_area.see(tk.END))

    def open_sound_test_window(self):
        threading.Thread(target=self.run_sound_test_once, daemon=True).start()

    def run_sound_test_once(self):
        if play_and_record_main is None:
            self.root.after(0, lambda: messagebox.showerror("Sound Test", "Sound test module not found."))
            return
        self.update_status("\nStarting single sound test...\n")
        try:
            result_corr = play_and_record_main()
            self.update_status(f"Sound test completed. Mean correlation: {result_corr:.4f}\n")
            status = "succeeded" if result_corr >= self.sound_threshold else "failed"
            msg_func = messagebox.showinfo if status == "succeeded" else messagebox.showerror
            self.root.after(0, lambda: msg_func("Sound Test", f"Sound test {status} (corr={result_corr:.4f})"))
        except Exception as e:
            self.update_status(f"[ERROR] Sound Test Exception: {e}\n")
            self.root.after(0, lambda: messagebox.showerror("Sound Test", f"Exception: {e}"))

    def open_storage_window(self):
        if StorageTestApp is None:
            messagebox.showerror("Storage Test", "StorageTestApp module not found.")
            return
        storage_window = tk.Toplevel(self.root)
        storage_window.title("Storage Test")
        storage_window.geometry("600x500")
        StorageTestApp(storage_window)

    def open_network_test_window(self):
        if NetworkTestApp is None:
            messagebox.showerror("Network Test", "NetworkTestApp module not found.")
            return
        net_window = tk.Toplevel(self.root)
        net_window.title("Network Test")
        net_window.geometry("400x350")
        NetworkTestApp(net_window)

    def _update_storage_progress(self, index, percent):
        self.update_status(f"[Storage] Device {index+1} progress: {percent:.1f}%")

    def reset_system_info(self):
        self.info_area.delete("1.0", tk.END)
        self.info_area.insert(tk.END, "System Information will appear here.\n")
        self.display_system_info()

    def display_system_info(self):
        self.update_status("CPU Info:\n" + get_cpu_info() + "\n")
        self.update_status("GPU Info:\n" + get_gpu_info() + "\n")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    root = tk.Tk()
    app = LoadTestApp(root)
    app.start_update_loop()
    root.protocol("WM_DELETE_WINDOW", app.exit_app)
    root.mainloop()
