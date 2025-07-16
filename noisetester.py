# sound_test/noisetester.py
import sounddevice as sd
import numpy as np

def play_and_record_main(duration=1.0, samplerate=44100, channels=1):
    """
    1kHzサイン波を再生しつつ録音、相互相関を返します。
    振幅を大きくし、sd.playrecで一括再生録音する方式に変更。
    """
    # --- テストトーン生成 (1kHz, 振幅0.8) ---
    N = int(samplerate * duration)
    t = np.linspace(0, duration, N, endpoint=False)
    freq = 1000  # 1kHz
    # 振幅を0.8にアップ
    tone = (0.8 * np.sin(2 * np.pi * freq * t)).astype('float32')

    # --- 再生 + 録音を一発で ---
    try:
        # playrec: 再生しながら同サイズの録音バッファを返す
        recording = sd.playrec(
            tone,
            samplerate=samplerate,
            channels=channels,
            dtype='float32'
        )
        sd.wait()  # 完了までブロック
        # playrecは (frames, channels) の形で返るので1次元化
        recording = recording.flatten()
    except Exception as e:
        print(f"[ERROR] Could not play/record: {e}")
        # 録音失敗時は相関 0.0 でスキップ
        return 0.0

    # --- 相互相関を計算し、正規化して返す ---
    # tone と recording の長さが同じなので 'full' で計算
    corr = np.correlate(recording, tone, mode='full')
    # 真ん中で最大値
    if corr.size > 0:
        norm = np.sqrt(np.dot(recording, recording) * np.dot(tone, tone))
        return float(np.max(corr) / norm) if norm != 0 else 0.0
    return 0.0
