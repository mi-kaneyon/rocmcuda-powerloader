import threading
import multiprocessing

def run_cpu_load_wrapper(cpu_func, cpu_load_percentage, stop_event):
    # CPU負荷テスト呼び出し
    cpu_func(cpu_load_percentage, stop_event)

def run_gpu_load_wrapper(gpu_func, gpu_load_percentage, gpu_ids, stop_event):
    # GPU負荷テスト呼び出し
    gpu_func(gpu_load_percentage, stop_event, gpu_ids)



def stop_all_tests(app):
    # すべての stop_event をセット
    for ev in getattr(app,'__dict__',{}):
        if ev.endswith('_stop_event') and app.__dict__[ev]:
            app.__dict__[ev].set()
    # join 
    threading.Thread(target=lambda: None,daemon=True).start()


def join_all_threads(app):
    threads = app.cpu_threads + app.gpu_threads
    for t in (app.storage_test_thread, app.sound_test_thread, app.network_test_thread):
        if t:
            threads.append(t)
    for th in threads:
        if th.is_alive():
            th.join(timeout=5)
    # プロセス停止
    for p in app.cpu_processes:
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)

    # クリア
    app.cpu_threads.clear(); app.cpu_processes.clear(); app.gpu_threads.clear()
    app.storage_test_thread = None; app.sound_test_thread = None; app.network_test_thread = None

    app.root.after(0, lambda: app.update_status("\nAll tests stopped.\n"))
    app.root.after(0, app.set_ui_state, False)


# --- util/result_manager.py ---
import tkinter as tk
from tkinter import ttk

def show_summary_window(app):
    win = tk.Toplevel(app.root)
    win.title("Burn-in Test Summary")
    win.geometry("400x300")
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Test Results", font=("Helvetica", 16, "bold")).pack(pady=10)
    colors = {"PASS":"green","FAIL":"red","SKIP":"gray"}
    for name, res in app.test_results.items():
        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=f"{name}:", width=10, anchor="w").pack(side=tk.LEFT)
        ttk.Label(row, text=res, foreground=colors.get(res), font=("Helvetica",12,"bold")).pack(side=tk.LEFT)
    ttk.Button(frame, text="Close", command=win.destroy).pack(pady=15)
