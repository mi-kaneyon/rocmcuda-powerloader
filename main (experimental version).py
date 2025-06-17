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

# --- モジュールインポート ---
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
    time.sleep(3) # マイクの準備時間

    if play_and_record_main is None:
        app.root.after(0, lambda: info_area.insert(tk.END, "[Sound Loop] Sound test module not found.\n"))
        app.test_results["Sound"] = "SKIP"
        return

    results = []
    end_time = time.time() + duration
    app.test_results["Sound"] = "FAIL"

    # 時間が経過するか、停止信号が来るまでループ
    while time.time() < end_time and not stop_event.is_set():
        try:
            mean_corr = play_and_record_main()
            results.append(mean_corr)
            app.root.after(0, lambda mc=mean_corr: info_area.insert(tk.END, f"[Sound Loop] Mean correlation: {mc:.4f}\n"))
        except Exception as e:
            app.root.after(0, lambda err=e: info_area.insert(tk.END, f"[Sound Loop] Exception: {err}\n"))
            # 例外発生時はFAILのまま終了
            return

        # 次のテストまで少し待機 (stop_eventを監視)
        if stop_event.wait(timeout=3):
            break

    # 最終判定
    if not results:
        app.test_results["Sound"] = "SKIP"
    elif any(r >= sound_threshold for r in results):
        app.test_results["Sound"] = "PASS"
    # それ以外はデフォルトのFAILのまま

def run_storage_test_wrapper(app, storage_instance, progress_callback, stop_event, duration):
    start_event.wait()
    if stop_event.is_set():
        app.test_results["Storage"] = "SKIP"
        return

    app.test_results["Storage"] = "FAIL"

    def monitor_stop():
        stop_event.wait()
        if storage_instance:
            storage_instance.stop_test()
            app.root.after(0, lambda: app.update_status("[Storage Test] Stop signal received, attempting to halt."))
    
    monitor_thread = threading.Thread(target=monitor_stop, daemon=True)
    monitor_thread.start()

    try:
        storage_instance.run_storage_test(progress_callback, duration)
        if not stop_event.is_set():
            app.test_results["Storage"] = "PASS"
        else:
            app.test_results["Storage"] = "SKIP"
            
    except Exception as e:
        app.root.after(0, lambda e=e: app.update_status(f"[Storage Test] Exception: {e}"))


def run_network_test_wrapper(app, stop_event, net_area, duration):
    """
    指定された時間、バックグラウンドで nettest.py のループを実行し、結果を監視する。
    """
    if run_network_test_loop is None:
        app.root.after(0, lambda: net_area.insert(tk.END, "[Network Test] Module not found.\n"))
        app.test_results["Network"] = "SKIP"
        return

    start_event.wait()
    
    app.test_results["Network"] = "FAIL"
    any_success = False
    any_failure = False

    def callback(target, result):
        nonlocal any_success, any_failure
        
        # resultが辞書の場合、簡易的な文字列に変換
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
        else: # 文字列の場合
            res_str = str(result)
            if "fail" in res_str.lower() or "error" in res_str.lower():
                any_failure = True
            else:
                any_success = True

        app.root.after(0, lambda t=target, r=res_str: net_area.insert(tk.END, f"→ {t}: {r}\n"))
        app.root.after(0, net_area.see, tk.END)

    # run_network_test_loopをバックグラウンドで実行するスレッド
    # このスレッドはstop_eventで停止する
    network_thread = threading.Thread(
        target=run_network_test_loop,
        args=(stop_event, callback),
        daemon=True  # メインスレッドが終了すれば一緒に終了する
    )
    network_thread.start()
    
    # このラッパー関数は、指定時間待機する役割に徹する
    # stop_event.wait() を使うことで、手動停止にも即座に反応できる
    stop_event.wait(timeout=duration)
    
    # 待機が終わったら、ループを止めるために再度イベントをセット
    if not stop_event.is_set():
        stop_event.set()

    # 最終判定
    if any_success and not any_failure:
        app.test_results["Network"] = "PASS"
    elif not any_success and not any_failure:
        app.test_results["Network"] = "SKIP"

    # stop_eventがセットされるまでループ
    while not stop_event.is_set():
        for target in targets:
            if stop_event.is_set(): break
            
            result_str = ping_target(target)
            app.root.after(0, lambda r=result_str: net_area.insert(tk.END, r + "\n"))
            
            if "FAIL" in result_str or "Error" in result_str:
                any_failure = True
            else:
                any_success = True

        # 次のpingまで待機。stop_eventを監視することで、待機中でも停止できる。
        if stop_event.wait(timeout=interval):
            break
    
    # 最終判定
    if any_success and not any_failure:
        app.test_results["Network"] = "PASS"
    elif not any_success and not any_failure:
        # 一度も実行されなかった
        app.test_results["Network"] = "SKIP"
    # それ以外はデフォルトのFAILのまま

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
    
    def apply_load(self):
        if self.burn_in_active:
            messagebox.showwarning("Test in Progress", "Cannot start individual load while burn-in test is active.")
            return

        self.stop_all_tests()
        self.set_ui_state(True)
        
        if self.cpu_load_type.get() == "x86":
            self.stop_event = multiprocessing.Event()
        else:
            self.stop_event = threading.Event()
        
        cpu_load_percentage = self.cpu_load.get()
        gpu_load_percentage = self.gpu_load.get()
        gpu_vram_percentage = self.gpu_vram_load.get()
        cpu_load_type = self.cpu_load_type.get()
        gpu_load_type = self.gpu_load_type.get()

        self.update_status(f"\nApplying individual loads...\n")
        self.update_status(f"CPU Load: {cpu_load_percentage}% ({cpu_load_type})")
        self.update_status(f"GPU Load: {gpu_load_percentage}% ({gpu_load_type})")
        self.update_status(f"VRAM Load: {gpu_vram_percentage}%\n")

        if cpu_load_percentage > 0 and (apply_cpu_load and apply_cpu_load_x86):
            if cpu_load_type == "x86":
                p = multiprocessing.Process(target=apply_cpu_load_x86, args=(cpu_load_percentage, self.stop_event))
                self.cpu_processes.append(p)
                p.start()
            else:
                t = threading.Thread(target=apply_cpu_load, args=(cpu_load_percentage, self.stop_event), daemon=True)
                self.cpu_threads.append(t)
                t.start()

        if torch.cuda.is_available():
            gpu_ids = list(range(torch.cuda.device_count()))
            if gpu_load_percentage > 0 and (apply_combined_load or apply_gpu_tensor_load):
                gpu_func = apply_combined_load if gpu_load_type == "3D Render" else apply_gpu_tensor_load
                t = threading.Thread(target=gpu_func, args=(gpu_load_percentage, self.stop_event, gpu_ids), daemon=True)
                self.gpu_threads.append(t)
                t.start()
            if gpu_vram_percentage > 0 and apply_gpu_vram_load:
                t = threading.Thread(target=apply_gpu_vram_load, args=(gpu_vram_percentage, self.stop_event, gpu_ids), daemon=True)
                self.gpu_threads.append(t)
                t.start()

    def set_ui_state(self, is_testing):
        state = "disabled" if is_testing else "normal"
        self.start_button.config(state=state)
        self.burnin_button.config(state=state)
        self.storage_test_button.config(state=state)
        self.sound_test_button.config(state=state)
        self.network_test_button.config(state=state)
        self.cpu_slider.config(state=state)
        self.gpu_slider.config(state=state)
        self.gpu_vram_slider.config(state=state)
        self.burnin_entry.config(state=state)
        self.stress_combo.config(state=state)

    def run_burn_in_test(self):
        if self.burn_in_active:
            messagebox.showwarning("Burn-in Test", "A burn-in test is already running.")
            return
        
        try:
            duration = int(self.burnin_duration.get())
            if duration <= 0: raise ValueError
        except (ValueError, TypeError):
            messagebox.showerror("Input Error", "Invalid burn-in duration. Must be a positive number.")
            return

        stress = self.stress_level.get()
        cpu_val, gpu_val, vram_val = {"Low": (30, 30, 30), "Mid": (60, 60, 60), "High": (80, 80, 80)}[stress]
        
        self.burn_in_active = True
        self.set_ui_state(True)
        self.cpu_load.set(cpu_val)
        self.gpu_load.set(gpu_val)
        self.gpu_vram_load.set(vram_val)
        self.update_status(f"\nStarting Burn-in Test for {duration} sec at {stress} level...\n")

        self.test_results = {key: "SKIP" for key in self.test_results}
        self.stop_event = threading.Event()
        self.burnin_stop_event.clear()
        start_event.clear()
        
        if self.cpu_load.get() > 0 and apply_cpu_load and apply_cpu_load_x86:
            self.test_results["CPU"] = "PASS" 
            try:
                cpu_func = apply_cpu_load_x86 if self.cpu_load_type.get() == "x86" else apply_cpu_load
                if self.cpu_load_type.get() == "x86":
                    p = multiprocessing.Process(target=run_cpu_load_wrapper, args=(cpu_func, self.cpu_load.get(), self.stop_event))
                    self.cpu_processes.append(p)
                    p.start()
                else:
                    t = threading.Thread(target=run_cpu_load_wrapper, args=(cpu_func, self.cpu_load.get(), self.stop_event), daemon=True)
                    self.cpu_threads.append(t)
                    t.start()
            except Exception as e:
                self.test_results["CPU"] = "FAIL"
                self.update_status(f"[CPU Test] Failed to start: {e}")
        
        num_gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0
        if num_gpus > 0:
            gpu_ids = list(range(num_gpus))
            if self.gpu_load.get() > 0 and (apply_combined_load and apply_gpu_tensor_load):
                self.test_results["GPU"] = "PASS"
                try:
                    gpu_func = apply_combined_load if self.gpu_load_type.get() == "3D Render" else apply_gpu_tensor_load
                    t = threading.Thread(target=run_gpu_load_wrapper, args=(gpu_func, self.gpu_load.get(), gpu_ids, self.stop_event), daemon=True)
                    self.gpu_threads.append(t)
                    t.start()
                except Exception as e:
                    self.test_results["GPU"] = "FAIL"
                    self.update_status(f"[GPU Test] Failed to start: {e}")

            if self.gpu_vram_load.get() > 0 and apply_gpu_vram_load:
                self.test_results["VRAM"] = "PASS"
                try:
                    t = threading.Thread(target=run_gpu_load_wrapper, args=(apply_gpu_vram_load, self.gpu_vram_load.get(), gpu_ids, self.stop_event), daemon=True)
                    self.gpu_threads.append(t)
                    t.start()
                except Exception as e:
                    self.test_results["VRAM"] = "FAIL"
                    self.update_status(f"[VRAM Test] Failed to start: {e}")

        if StorageTest:
            self.storage_test_instance = StorageTest(gui_callback=self.update_status)
            self.storage_test_instance.detect_usb_devices()
            self.storage_test_thread = threading.Thread(
                target=run_storage_test_wrapper,
                args=(self, self.storage_test_instance, self._update_storage_progress, self.stop_event, duration),
                daemon=True
            )
            self.storage_test_thread.start()
        
        # --- ネットワークテストの起動 (修正箇所) ---
        if run_network_test_loop:
            self.net_popup, self.net_progress = create_net_popup(self.root)
            self.network_test_thread = threading.Thread(
                target=run_network_test_wrapper,
                # args に duration を追加
                args=(self, self.stop_event, self.net_progress, duration),
                daemon=True
            )
            self.network_test_thread.start()

        if play_and_record_main:
            self.burnin_popup, self.burnin_progress = create_burnin_popup(self.root)
            self.sound_test_thread = threading.Thread(target=run_sound_test_wrapper, args=(self, self.stop_event, self.burnin_progress, self.sound_threshold, duration), daemon=True)
            self.sound_test_thread.start()

        start_event.set()
        threading.Thread(target=self._burn_in_timer, args=(duration,), daemon=True).start()

    def _burn_in_timer(self, duration):
        completed_fully = not self.burnin_stop_event.wait(timeout=duration)
        self.root.after(0, self.stop_all_tests, lambda: self._on_test_done(completed_fully))

    def _on_test_done(self, completed_fully):
        if not completed_fully:
            self.update_status("\nBurn-in Test was stopped manually.\n")
        else:
            self.update_status("\nBurn-in Test completed.\n")
        
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
    
    def stop_all_tests(self, on_done_callback=None):
        if self.stop_event: self.stop_event.set()
        self.burnin_stop_event.set()
        self.update_status("\nStop signal sent. Waiting for tests to terminate...\n")

        if self.burnin_popup and self.burnin_popup.winfo_exists(): self.burnin_popup.destroy()
        if self.net_popup and self.net_popup.winfo_exists(): self.net_popup.destroy()

        threading.Thread(target=self._join_all_threads, args=(on_done_callback,), daemon=True).start()

    def _join_all_threads(self, on_done_callback=None):
        all_threads = self.cpu_threads + self.gpu_threads
        if self.storage_test_thread: all_threads.append(self.storage_test_thread)
        if self.sound_test_thread: all_threads.append(self.sound_test_thread)
        if self.network_test_thread: all_threads.append(self.network_test_thread)
        
        for thread in all_threads:
            if thread and thread.is_alive(): thread.join(timeout=5)
        
        for process in self.cpu_processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

        self.cpu_threads.clear(); self.cpu_processes.clear(); self.gpu_threads.clear()
        self.storage_test_thread = self.sound_test_thread = self.network_test_thread = None
        
        if on_done_callback:
            self.root.after(0, on_done_callback)
        else:
            self.root.after(0, lambda: self.update_status("\nAll tests have been stopped.\n"))
            self.root.after(0, self.set_ui_state, False)

    def update_system_info(self):
        try:
            psu_power = get_psu_power()
            cpu_usage = psutil.cpu_percent()
            memory_usage = psutil.virtual_memory().percent

            vram_usage = 0
            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                total_mem = sum(torch.cuda.get_device_properties(i).total_memory for i in range(torch.cuda.device_count()))
                allocated_mem = sum(torch.cuda.memory_allocated(i) for i in range(torch.cuda.device_count()))
                if total_mem > 0: vram_usage = (allocated_mem / total_mem) * 100

            self.psu_power_label.config(text=psu_power)
            self.cpu_usage_label.config(text=f"CPU Usage: {cpu_usage}%")
            self.memory_usage_label.config(text=f"Memory Usage: {memory_usage}%")
            self.gpu_vram_label.config(text=f"VRAM Usage: {vram_usage:.2f}%")
        except Exception as e:
            print(f"Error updating system info: {e}")
        finally:
            self.update_loop_id = self.root.after(2000, self.update_system_info)

    def start_update_loop(self):
        if self.update_loop_id: self.root.after_cancel(self.update_loop_id)
        psutil.cpu_percent() 
        self.update_system_info()
    
    def exit_app(self):
        if self.burn_in_active and not messagebox.askyesno("Exit", "A burn-in test is running. Are you sure you want to exit?"):
            return
        self.stop_all_tests()
        self.root.after(200, self._final_exit)

    def _final_exit(self):
        if self.update_loop_id: self.root.after_cancel(self.update_loop_id)
        self.root.quit()
        self.root.destroy()
        os._exit(0)

    def update_status(self, message):
        if self.root.winfo_exists():
            self.root.after(0, lambda: self.info_area.insert(tk.END, message + "\n"))
            self.root.after(0, lambda: self.info_area.see(tk.END))

    def open_sound_test_window(self): threading.Thread(target=self.run_sound_test_once, daemon=True).start()
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
        storage_window.title("Storage Test"); storage_window.geometry("600x500")
        StorageTestApp(storage_window)

    def open_network_test_window(self):
        if NetworkTestApp is None:
            messagebox.showerror("Network Test", "NetworkTestApp module not found.")
            return
        net_window = tk.Toplevel(self.root)
        net_window.title("Network Test"); net_window.geometry("400x350")
        NetworkTestApp(net_window)

    def _update_storage_progress(self, index, percent): self.update_status(f"[Storage] Device {index+1} progress: {percent:.1f}%")
    
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
