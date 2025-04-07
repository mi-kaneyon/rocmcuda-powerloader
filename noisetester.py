#!/usr/bin/env python3
import os
import sys
import sounddevice as sd
import numpy as np
import matplotlib
# Use the Agg backend to avoid GUI display for matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
from datetime import datetime

# Suppress matplotlib warnings about missing glyphs
warnings.filterwarnings("ignore", category=UserWarning, module='matplotlib.font_manager')

# -----------------------------
# Global settings
# -----------------------------
RATE = 44100                   # サンプリングレート
DURATION_PRETEST = 3           # Pre‑test のテスト時間（秒）
DURATION_MAIN = 30             # Main test のテスト時間（秒）
FREQUENCY = 1000               # サイン波の周波数 (Hz)
CHANNELS = 1                   # モノラル
PRETEST_THRESHOLD = 0.4        # Pre‑test 相関の閾値
DEFAULT_AMPLITUDE = 1.0        # 発振波形の振幅（最大出力を想定）

# -----------------------------
# Sine Wave Generation
# -----------------------------
def generate_sine_wave(frequency, duration, rate, amplitude=1.0):
    """
    Generate a sine wave with given frequency, duration, and amplitude.
    """
    t = np.linspace(0, duration, int(rate * duration), endpoint=False)
    return amplitude * np.sin(2 * np.pi * frequency * t)

# -----------------------------
# Play and Record Function
# -----------------------------
def _play_and_record_once(duration, device_index, amplitude=1.0):
    """
    Play a sine wave and record simultaneously for 'duration' seconds on the specified device.
    The sine wave is generated with the specified amplitude.
    Returns the recorded data array.
    """
    sine_wave = generate_sine_wave(FREQUENCY, duration, RATE, amplitude)
    recorded_data = np.zeros((int(RATE * duration), CHANNELS), dtype=np.float32)

    def callback(in_data, out_data, frames, time_info, status):
        start = callback.frame
        # Playback
        if start >= len(sine_wave):
            out_data[:] = 0
        else:
            frames_to_copy = min(len(sine_wave) - start, frames)
            out_data[:frames_to_copy] = sine_wave[start:start+frames_to_copy].reshape(-1, CHANNELS)
            if frames_to_copy < frames:
                out_data[frames_to_copy:] = 0
        # Recording
        frames_to_copy = min(len(recorded_data) - start, frames)
        if frames_to_copy > 0:
            chunk = np.frombuffer(in_data, dtype=np.float32).reshape(-1, CHANNELS)
            recorded_data[start:start+frames_to_copy] = chunk[:frames_to_copy]
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
# Correlation Computation
# -----------------------------
def compute_correlation_global(sine_wave, recorded_data):
    """
    Compute a global correlation value between the generated sine_wave and recorded_data.
    """
    if recorded_data is None or np.max(np.abs(recorded_data)) < 1e-8:
        return 0.0
    sw_norm = sine_wave / np.max(np.abs(sine_wave))
    rd_norm = recorded_data.flatten() / np.max(np.abs(recorded_data))
    scaling_factor = np.max(np.abs(sine_wave)) / (np.max(np.abs(recorded_data)) + 1e-8)
    rd_scaled = recorded_data.flatten() * scaling_factor
    rd_scaled_norm = rd_scaled / np.max(np.abs(rd_scaled))
    corr = np.corrcoef(sw_norm, rd_scaled_norm)[0, 1]
    return abs(corr)

# -----------------------------
# Device Selection with Pre-test
# -----------------------------
def select_device_with_pretest():
    """
    Query available sound devices and perform a short pre-test (3s) on candidates.
    Returns the index of the device with highest correlation above PRETEST_THRESHOLD.
    """
    devices = sd.query_devices()
    print("Available sound devices:")
    for idx, dev in enumerate(devices):
        print(f"Device {idx}: {dev['name']} (In: {dev['max_input_channels']}, Out: {dev['max_output_channels']})")
    
    candidate_indices = [idx for idx, dev in enumerate(devices)
                         if dev["max_input_channels"] > 0 and dev["max_output_channels"] > 0]
    if not candidate_indices:
        print("No full-duplex device found. Fallback to OS default.")
        return None

    pretest_sine = generate_sine_wave(FREQUENCY, DURATION_PRETEST, RATE, amplitude=DEFAULT_AMPLITUDE)
    best_idx = None
    best_corr = 0.0
    for idx in candidate_indices:
        print(f"Pre-test on device {idx}: {devices[idx]['name']}")
        rec_data = _play_and_record_once(DURATION_PRETEST, idx, amplitude=DEFAULT_AMPLITUDE)
        corr = compute_correlation_global(pretest_sine, rec_data)
        print(f" --> correlation = {corr:.4f}")
        if corr >= PRETEST_THRESHOLD and corr > best_corr:
            best_corr = corr
            best_idx = idx

    if best_idx is not None:
        print(f"Selected device {best_idx} (corr={best_corr:.4f}) for main test.")
    else:
        print("No device passed pre-test. Using OS default device.")
    return best_idx

# -----------------------------
# Main Test Function
# -----------------------------
def play_and_record_main():
    """
    Perform the main test (30s) using the device selected by the pre-test.
    Returns the average correlation coefficient over segments.
    """
    selected_idx = select_device_with_pretest()
    if selected_idx is not None:
        sd.default.device = (selected_idx, selected_idx)
    else:
        sd.default.device = None

    print("Generating main sine wave for 30s test...")
    sine_wave = generate_sine_wave(FREQUENCY, DURATION_MAIN, RATE, amplitude=DEFAULT_AMPLITUDE)
    rec_data = _play_and_record_once(DURATION_MAIN,
                                     selected_idx if selected_idx is not None else sd.default.device[0],
                                     amplitude=DEFAULT_AMPLITUDE)
    if rec_data is None:
        print("[ERROR] Main test: no recorded data.")
        return 0.0

    # Segment-based correlation calculation
    segment_duration = 2
    start_time = 3
    end_time = DURATION_MAIN - segment_duration
    correlations = []
    segment_times = []
    while start_time <= end_time:
        start_sample = int(RATE * start_time)
        end_sample = int(RATE * (start_time + segment_duration))
        sw_segment = sine_wave[start_sample:end_sample]
        rd_segment = rec_data.flatten()[start_sample:end_sample]
        if np.max(np.abs(rd_segment)) < 1e-8:
            correlations.append(0.0)
            segment_times.append(start_time)
            start_time += segment_duration
            continue

        sw_norm = sw_segment / np.max(np.abs(sw_segment))
        rd_norm = rd_segment / np.max(np.abs(rd_segment))
        scaling_factor = np.max(np.abs(sw_segment)) / (np.max(np.abs(rd_segment)) + 1e-8)
        rd_scaled = rd_segment * scaling_factor
        rd_scaled_norm = rd_scaled / np.max(np.abs(rd_scaled))
        rd_inverted = -rd_scaled_norm

        corr = np.corrcoef(sw_norm, rd_scaled_norm)[0, 1]
        corr_inv = np.corrcoef(sw_norm, rd_inverted)[0, 1]
        final_corr = corr if abs(corr) > abs(corr_inv) else corr_inv
        print(f"Segment {start_time}-{start_time+segment_duration}s: Corr = {final_corr:.4f}")
        correlations.append(abs(final_corr))
        segment_times.append(start_time)
        start_time += segment_duration

    mean_corr = np.mean(correlations)
    print(f"\nAverage Correlation Coefficient: {mean_corr:.4f}")
    if mean_corr > 0.6:
        print("Test Result: Sound test success!")
    else:
        print("Test Result: Sound test failed.")

    # Plotting results
    current_date = datetime.now().strftime("%Y%m%d")
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
        plt.axvline(x=st+segment_duration, color='red', linestyle='--', alpha=0.7)
    plt.title('Recorded Signal with Segment Boundaries')
    plt.xlabel('Time (s)')
    plt.ylabel('Amplitude')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{current_date}_original_recorded_signals.png")
    plt.close()

    plt.figure(figsize=(10,5))
    plt.plot(segment_times, correlations, marker='o', linestyle='-', color='blue')
    plt.title('Correlation Coefficient for Each Segment')
    plt.xlabel('Start Time of Segment (s)')
    plt.ylabel('Absolute Correlation Coefficient')
    plt.ylim(0,1)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(f"{current_date}_correlation_coefficients.png")
    plt.close()

    return mean_corr

# -----------------------------
# If run directly, execute main test
# -----------------------------
if __name__ == "__main__":
    final_corr = play_and_record_main()
    print(f"Final correlation: {final_corr:.4f}")
