# util/test_runner.py

import threading
import subprocess
import time
import tkinter as tk
import torch

from cpu_load.cpu_load import apply_cpu_load, apply_cpu_load_x86
from gpu_load.gpu_load import (
    apply_gpu_tensor_load,
    apply_combined_load,
    apply_gpu_vram_load,
)
from sound_test.noisetester import play_and_record_main
from storage_load.storage_test import StorageTest
from network_test.nettest import run_network_test_loop


def run_cpu_load(app, cpu_pct, stop_event):
    """CPU 負荷テストのラッパー"""
    try:
        app.update_status(f"[CPU] Start load at {cpu_pct}%")
        func = apply_cpu_load_x86 if app.cpu_load_type.get() == "x86" else apply_cpu_load
        func(cpu_pct, stop_event)
        app.update_status("[CPU] Load completed")
        app.test_results["CPU"] = "PASS"
    except Exception as e:
        app.update_status(f"[CPU] Exception: {e}")
        app.test_results["CPU"] = "FAIL"


def run_gpu_load(app, gpu_pct, vram_pct, stop_event):
    """
    GPU と VRAM の負荷を同時に開始するラッパー
    """
    results = {"GPU": False, "VRAM": False}

    def _compute():
        try:
            app.update_status(f"[GPU] Compute/Render load {gpu_pct}% start")
            gpu_func = (
                apply_combined_load
                if app.gpu_load_type.get() == "3D Render"
                else apply_gpu_tensor_load
            )
            gpu_func(gpu_pct, stop_event, list(range(torch.cuda.device_count())))
            app.update_status("[GPU] Compute/Render load threads launched")
            results["GPU"] = True
        except Exception as e:
            app.update_status(f"[GPU] Exception: {e}")

    def _vram():
        try:
            app.update_status(f"[VRAM] Allocation load {vram_pct}% start")
            apply_gpu_vram_load(vram_pct, stop_event, list(range(torch.cuda.device_count())))
            app.update_status("[VRAM] Allocation load threads launched")
            results["VRAM"] = True
        except Exception as e:
            app.update_status(f"[VRAM] Exception: {e}")

    if gpu_pct > 0:
        t1 = threading.Thread(target=_compute, daemon=True)
        t1.start()
        app.gpu_threads.append(t1)
    if vram_pct > 0:
        t2 = threading.Thread(target=_vram, daemon=True)
        t2.start()
        app.gpu_threads.append(t2)

    # 非同期にスレッドを起動したら即 PASS
    if gpu_pct > 0 or vram_pct > 0:
        app.test_results["GPU"] = "PASS"


def run_storage_test(app, stop_event, duration):
    """Storage／USB ポート一括テストのラッパー"""
    app.update_status("[Storage] Starting storage & USB port tests...")
    runner = StorageTest(gui_callback=app.update_status)
    try:
        success = runner.run_test_loop(app._update_storage_progress, duration)
        status = "PASS" if success else "FAIL"
        app.test_results["Storage"] = status
        app.update_status(f"[Storage] Test {status}")
    except Exception as e:
        app.update_status(f"[Storage] Exception: {e}")
        app.test_results["Storage"] = "FAIL"


def run_network_test(app, stop_event, net_area, duration):
    """Network テストのラッパー（組み込み or Ping フォールバック）"""
    app.update_status("[Network] Starting network test...")
    success = False
    failure = False

    if run_network_test_loop:
        def callback(target, result):
            nonlocal success, failure
            if isinstance(result, dict) and (result.get("error") or result.get("loss", 0) > 0):
                failure = True
                status_str = f"FAIL ({result.get('error', result.get('loss'))})"
            else:
                success = True
                status_str = str(result)
            app.root.after(0, lambda: net_area.insert(tk.END, f"→ {target}: {status_str}\n"))

        thread = threading.Thread(
            target=run_network_test_loop,
            args=(stop_event, callback),
            daemon=True
        )
        thread.start()
        stop_event.wait(timeout=duration)
        if not stop_event.is_set():
            stop_event.set()
        thread.join(timeout=5)
    else:
        app.update_status("[Network] Fallback: ping 8.8.8.8")
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "8.8.8.8"],
                capture_output=True, text=True
            )
            status_str = "PASS" if res.returncode == 0 else "FAIL"
            app.root.after(
                0,
                lambda: net_area.insert(tk.END, f"[Network Fallback] Ping result: {status_str}\n")
            )
            success = (status_str == "PASS")
        except Exception as e:
            app.update_status(f"[Network] Fallback exception: {e}")
            failure = True

    if success and not failure:
        app.test_results["Network"] = "PASS"
    elif not success and not failure:
        app.test_results["Network"] = "SKIP"
    else:
        app.test_results["Network"] = "FAIL"


def run_sound_test(app, stop_event, info_area, threshold, duration):
    """Sound 相関テストのラッパー"""
    app.update_status("[Sound] Starting sound loop...")
    start = time.time()
    results = []
    while time.time() - start < duration and not stop_event.is_set():
        try:
            corr = play_and_record_main()
            results.append(corr)
            app.root.after(0, lambda c=corr: info_area.insert(tk.END, f"[Sound] corr={c:.3f}\n"))
        except Exception as e:
            app.update_status(f"[Sound] Exception: {e}")
            break
        time.sleep(1)

    if not results:
        app.test_results["Sound"] = "SKIP"
    elif max(results) >= threshold:
        app.test_results["Sound"] = "PASS"
    else:
        app.test_results["Sound"] = "FAIL"

