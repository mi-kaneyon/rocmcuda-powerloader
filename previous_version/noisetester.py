#!/usr/bin/env python3
import os, sys
import sounddevice as sd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
from datetime import datetime
from scipy.signal import butter, sosfiltfilt, correlate
warnings.filterwarnings("ignore", category=UserWarning, module='matplotlib.font_manager')

# -----------------------------
# Global settings
# -----------------------------
RATE = 44100
DURATION_PRETEST = 3
DURATION_MAIN = 30
FREQUENCY = 1000
CHANNELS = 1
PRETEST_THRESHOLD = 0.4
DEFAULT_AMPLITUDE = 1.0
SOUND_TRIALS = 5       # 複数試行の回数
FILTER_LOW = 300       # 帯域フィルタ下限 (Hz)
FILTER_HIGH = 3000     # 帯域フィルタ上限 (Hz)

# -----------------------------
# Sine wave generator
# -----------------------------
def generate_sine_wave(frequency, duration, rate, amplitude=1.0):
    t = np.linspace(0, duration, int(rate * duration), endpoint=False)
    return amplitude * np.sin(2 * np.pi * frequency * t)

# -----------------------------
# SOS bandpass filter (zero-phase)
# -----------------------------
def sos_bandpass_filter(data, sr, lowcut, highcut, order=4):
    sos = butter(order, [lowcut, highcut], btype='band', fs=sr, output='sos')
    return sosfiltfilt(sos, data)

# -----------------------------
# 安定版ラッパー関数：複数試行＋中央値評価
# -----------------------------
def stable_play_and_record(n_trials=SOUND_TRIALS):
    cors = []
    template = generate_sine_wave(FREQUENCY, DURATION_MAIN, RATE, amplitude=DEFAULT_AMPLITUDE)
    for i in range(n_trials):
        sig = play_and_record_main()
        if sig is None:
            cors.append(0.0)
            continue
        rec = sos_bandpass_filter(sig.flatten(), RATE, FILTER_LOW, FILTER_HIGH)
        corr = correlate(rec, template, mode='valid')
        cors.append(np.max(corr) / (np.linalg.norm(rec) * np.linalg.norm(template)))
    median_corr = float(np.median(cors))
    print(f"[stable] Trials={n_trials}, raw cors={cors}, median={median_corr:.4f}")
    return median_corr

# -----------------------------
# 一回再生／録音関数
# -----------------------------
def _play_and_record_once(duration, device_index, amplitude=DEFAULT_AMPLITUDE):
    sine_wave = generate_sine_wave(FREQUENCY, duration, RATE, amplitude)
    recorded_data = np.zeros((int(RATE * duration), CHANNELS), dtype=np.float32)

    def callback(in_data, out_data, frames, time_info, status):
        start = callback.frame
        if start >= len(sine_wave):
            out_data[:] = 0
        else:
            n = min(len(sine_wave) - start, frames)
            out_data[:n] = sine_wave[start:start+n].reshape(-1, CHANNELS)
            if n < frames:
                out_data[n:] = 0
        n = min(len(recorded_data) - start, frames)
        if n > 0:
            chunk = np.frombuffer(in_data, dtype=np.float32).reshape(-1, CHANNELS)
            recorded_data[start:start+n] = chunk[:n]
        callback.frame += frames

    callback.frame = 0
    try:
        with sd.Stream(samplerate=RATE, channels=CHANNELS, dtype='float32',
                       device=(device_index, device_index),
                       blocksize=1024, latency='low',
                       callback=callback):
            sd.sleep(int((duration + 0.5) * 1000))
    except Exception as e:
        print(f"[ERROR] Could not open stream on device {device_index}: {e}")
        return None

    return recorded_data

# -----------------------------
# グローバル相関計算（Pre-test用）
# -----------------------------
def compute_correlation_global(sine_wave, recorded_data):
    if recorded_data is None or np.max(np.abs(recorded_data)) < 1e-8:
        return 0.0
    sw = sine_wave / np.max(np.abs(sine_wave))
    rd = recorded_data.flatten()
    rd = rd * (np.max(np.abs(sine_wave)) / (np.max(np.abs(rd)) + 1e-8))
    rd = rd / np.max(np.abs(rd))
    corr = np.corrcoef(sw, rd)[0,1]
    return abs(corr)

# -----------------------------
# デバイス選定（Pre-test）
# -----------------------------
def select_device_with_pretest():
    devices = sd.query_devices()
    print("Available sound devices:")
    for idx, dev in enumerate(devices):
        print(f"Device {idx}: {dev['name']} (In: {dev['max_input_channels']}, Out: {dev['max_output_channels']})")

    candidates = [i for i,d in enumerate(devices) if d["max_input_channels"]>0 and d["max_output_channels"]>0]
    if not candidates:
        print("[WARN] No full-duplex device found.")
        return None

    sine = generate_sine_wave(FREQUENCY, DURATION_PRETEST, RATE, amplitude=DEFAULT_AMPLITUDE)
    best, best_corr = None, 0.0
    for idx in candidates:
        rec = _play_and_record_once(DURATION_PRETEST, idx)
        corr = compute_correlation_global(sine, rec)
        print(f"Pre-test device {idx}: corr={corr:.4f}")
        if corr>=PRETEST_THRESHOLD and corr>best_corr:
            best_corr, best = corr, idx

    if best is None:
        print("[WARN] No device passed pre-test; using default.")
    else:
        print(f"Selected device {best} with corr={best_corr:.4f}")
    return best

# -----------------------------
# 元の main テスト関数
# -----------------------------
def play_and_record_main():
    # デバイス選定
    selected = select_device_with_pretest()
    sd.default.device = (selected, selected) if selected is not None else None
    print("Running main test...")

    # 波形生成＆録音
    sine_wave = generate_sine_wave(FREQUENCY, DURATION_MAIN, RATE, amplitude=DEFAULT_AMPLITUDE)
    rec_data = _play_and_record_once(
        DURATION_MAIN,
        selected if selected is not None else sd.default.device[0]
    )
    if rec_data is None:
        print("[ERROR] no recorded data.")
        return None

    # セグメントごとの相関計算
    segment_duration = 2
    start_time = 3
    end_time = DURATION_MAIN - segment_duration
    segment_times = []
    correlations = []
    while start_time <= end_time:
        st = int(RATE * start_time)
        ed = int(RATE * (start_time + segment_duration))
        sw_segment = sine_wave[st:ed]
        rd_segment = rec_data.flatten()[st:ed]

        if np.max(np.abs(rd_segment)) < 1e-8:
            correlations.append(0.0)
            segment_times.append(start_time)
            start_time += segment_duration
            continue

        # 正規化＆相関計算
        sw_norm = sw_segment / np.max(np.abs(sw_segment))
        rd_scaled = rd_segment * (np.max(np.abs(sw_segment)) / (np.max(np.abs(rd_segment)) + 1e-8))
        rd_norm = rd_scaled / np.max(np.abs(rd_scaled))
        rd_inv  = -rd_norm

        corr_fwd = np.corrcoef(sw_norm, rd_norm)[0,1]
        corr_inv = np.corrcoef(sw_norm, rd_inv)[0,1]
        final_corr = corr_fwd if abs(corr_fwd) > abs(corr_inv) else corr_inv

        correlations.append(abs(final_corr))
        segment_times.append(start_time)
        print(f"Segment {start_time}-{start_time+segment_duration}s: corr={abs(final_corr):.4f}")
        start_time += segment_duration

    # 平均相関を計算
    mean_corr = np.mean(correlations)
    print(f"Mean corr={mean_corr:.4f}")
    print("Success" if mean_corr > 0.5 else "Fail")

    # --- プロット／保存 ---
    current_date = datetime.now().strftime("%Y%m%d")

    # 1) オリジナルと録音波形
    plt.figure(figsize=(12,6))
    plt.subplot(2,1,1)
    time_axis = np.linspace(0, DURATION_MAIN, len(sine_wave))
    plt.plot(time_axis, sine_wave, label='Original Sine Wave')
    plt.title('Original Sine Wave')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.grid(True)
    plt.legend()

    plt.subplot(2,1,2)
    time_axis = np.linspace(0, DURATION_MAIN, len(rec_data))
    plt.plot(time_axis, rec_data.flatten(), label='Recorded Signal')
    for st in segment_times:
        plt.axvline(x=st, color='red', linestyle='--', alpha=0.7)
        plt.axvline(x=st + segment_duration, color='red', linestyle='--', alpha=0.7)
    plt.title('Recorded Signal with Segment Boundaries')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{current_date}_original_recorded_signals.png")
    plt.close()

    # 2) セグメント相関プロット
    plt.figure(figsize=(10,5))
    plt.plot(segment_times, correlations, marker='o', linestyle='-')
    plt.title('Correlation Coefficient for Each Segment')
    plt.xlabel('Start Time of Segment (s)')
    plt.ylabel('Absolute Correlation Coefficient')
    plt.ylim(0, 1)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{current_date}_correlation_coefficients.png")
    plt.close()

    return mean_corr


# -----------------------------
# コマンドラインなら安定版を実行
# -----------------------------
if __name__ == "__main__":
    final = stable_play_and_record()
    print(f"Final median correlation: {final:.4f}")
