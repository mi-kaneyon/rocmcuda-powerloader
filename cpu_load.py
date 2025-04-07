#!/usr/bin/env python3
import subprocess
import os
import multiprocessing
import time

# x86命令を使ったCPU負荷テスト（全コア使用、待機時間とプロセスの優先度調整）
def apply_cpu_load_x86(load_percentage, stop_event, modulate=False):
    binary_path = os.path.join(os.path.dirname(__file__), "mixed_load")

    if not os.path.isfile(binary_path):
        print("[ERROR] 'mixed_load' binary not found. Make sure it is compiled and in the correct directory.")
        return

    if not os.access(binary_path, os.X_OK):
        os.chmod(binary_path, 0o755)

    def cpu_load_task(stop_event):
        try:
            # プロセス開始直後に優先度を下げる（Linuxの場合）
            try:
                os.nice(10)
            except Exception as e:
                print(f"[WARN] Failed to change process priority: {e}")
            while not stop_event.is_set():
                process = subprocess.Popen([binary_path, str(load_percentage)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                # 0.2秒ごとに停止チェック（modulateの場合は倍に）
                while not stop_event.is_set() and process.poll() is None:
                    time.sleep(0.2 * (2 if modulate else 1))
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                # 各ループ間に休止を入れる
                time.sleep(0.5 * (2 if modulate else 1))
        except Exception as e:
            print(f"[ERROR] Exception in cpu_load_task: {e}")

    num_processes = os.cpu_count()
    print(f"[DEBUG] Launching {num_processes} processes to apply x86 load.")
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=cpu_load_task, args=(stop_event,))
        processes.append(p)
        p.start()

    # 定期的に停止チェック
    while not stop_event.is_set():
        time.sleep(0.5)

    for p in processes:
        if p.is_alive():
            p.terminate()
        p.join()

# 通常のCPU負荷テスト（重い計算処理を行う）
def apply_cpu_load(load_percentage, stop_event, modulate=False):
    def cpu_intensive_task(stop_event):
        while not stop_event.is_set():
            # 計算処理を小さなチャンクに分け、各チャンク後に停止チェック
            for _ in range(5000):
                if stop_event.is_set():
                    break
                _ = [i ** 2 for i in range(1000)]
            if stop_event.is_set():
                break
            time.sleep(0.01 * (2 if modulate else 1))

    num_processes = os.cpu_count()
    print(f"[DEBUG] Launching {num_processes} processes to apply CPU load.")
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=cpu_intensive_task, args=(stop_event,))
        # 各プロセスの優先度を下げる
        try:
            p.start()
            os.nice(10)
        except Exception as e:
            print(f"[WARN] Failed to set process priority: {e}")
        processes.append(p)

    while not stop_event.is_set():
        time.sleep(0.5)

    for p in processes:
        if p.is_alive():
            p.terminate()
        p.join()
