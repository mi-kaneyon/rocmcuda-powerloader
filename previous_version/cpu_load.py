#!/usr/bin/env python3
import os
import subprocess
import time
from multiprocessing import Event, Process

# x86命令を使ったCPU負荷テスト（全コア使用、待機時間とプロセスの優先度調整）
def apply_cpu_load_x86(load_percentage: int, stop_event: Event, modulate: bool = False):
    """
    mixed_load バイナリを使って全コアに負荷をかける.
    stop_event は multiprocessing.Event で、セットされるとループを抜けて終了する.
    """
    binary_path = os.path.join(os.path.dirname(__file__), "mixed_load")

    if not os.path.isfile(binary_path):
        print("[ERROR] 'mixed_load' binary not found. Make sure it is compiled and in the correct directory.")
        return

    if not os.access(binary_path, os.X_OK):
        os.chmod(binary_path, 0o755)

    def cpu_load_task(stop_evt: Event):
        try:
            # プロセス開始直後に優先度を下げる（Linuxの場合）
            try:
                os.nice(10)
            except Exception as e:
                print(f"[WARN] Failed to change process priority: {e}")
            # 負荷ループ
            while not stop_evt.is_set():
                proc = subprocess.Popen(
                    [binary_path, str(load_percentage)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                # 0.2秒ごとに停止チェック（modulateなら倍遅く）
                interval = 0.2 * (2 if modulate else 1)
                while not stop_evt.is_set() and proc.poll() is None:
                    time.sleep(interval)
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait()
                # 各ループ間に休止
                time.sleep(0.5 * (2 if modulate else 1))
        except Exception as e:
            print(f"[ERROR] Exception in cpu_load_task: {e}")

    num_procs = os.cpu_count() or 1
    print(f"[DEBUG] Launching {num_procs} x86 load processes.")
    procs = []
    for _ in range(num_procs):
        p = Process(target=cpu_load_task, args=(stop_event,))
        p.start()
        procs.append(p)

    # 親プロセスでも停止監視
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()

    # 停止後のクリーンアップ
    for p in procs:
        if p.is_alive():
            p.terminate()
        p.join()


# 通常のCPU負荷テスト（重い計算処理を行う）
def apply_cpu_load(load_percentage: int, stop_event: Event, modulate: bool = False):
    """
    Pythonループによる負荷発生。
    stop_event がセットされると各チャンク後にループを抜ける.
    """
    def cpu_intensive_task(stop_evt: Event):
        try:
            while not stop_evt.is_set():
                # 計算処理を小さなチャンクに分割
                for _ in range(5000):
                    if stop_evt.is_set():
                        break
                    _ = [i * i for i in range(1000)]
                if stop_evt.is_set():
                    break
                # 少し休止して他スレッドへ譲る
                time.sleep(0.01 * (2 if modulate else 1))
        except Exception as e:
            print(f"[ERROR] Exception in cpu_intensive_task: {e}")

    num_procs = os.cpu_count() or 1
    print(f"[DEBUG] Launching {num_procs} Python CPU load processes.")
    procs = []
    for _ in range(num_procs):
        p = Process(target=cpu_intensive_task, args=(stop_event,))
        try:
            p.start()
            # 親プロセスの優先度を下げる
            os.nice(10)
        except Exception as e:
            print(f"[WARN] Failed to set process priority: {e}")
        procs.append(p)

    # 停止監視
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()

    # クリーンアップ
    for p in procs:
        if p.is_alive():
            p.terminate()
        p.join()


if __name__ == "__main__":
    # テスト実行用
    evt = Event()
    try:
        apply_cpu_load(50, evt)
    except KeyboardInterrupt:
        evt.set()
    print("CPU load test stopped.")
