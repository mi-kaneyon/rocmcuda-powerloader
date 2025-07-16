import tkinter as tk
from tkinter import ttk

# カラー設定
_COLORS = {"PASS": "green", "FAIL": "red", "SKIP": "gray"}

# エイリアス
show_summary = None  # 下部で定義後に代入します


def show_summary_window(app):
    """
    Burn-in Test の結果サマリーを表示するポップアップウィンドウを作成します。

    1) 全テスト結果から "FAIL" エントリを抽出し、
       FAIL があれば Overall=FAIL、なければ Overall=PASS と表示。
    2) FAIL がある場合は、失敗テスト名のみをリスト表示。
    3) "Close" ボタンをウィンドウ下部に常に配置。
    """
    # ウィンドウ生成
    win = tk.Toplevel(app.root)
    win.title("Test Summary")
    win.geometry("400x300")
    win.transient(app.root)

    # メインフレーム
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    # Overall 表示
    failures = [name for name, res in app.test_results.items() if res == "FAIL"]
    overall = "PASS" if not failures else "FAIL"
    ttk.Label(
        frame,
        text=f"Overall: {overall}",
        foreground=_COLORS.get(overall, "black"),
        font=(None, 16, "bold")
    ).pack(pady=(0, 10))

    # 詳細（FAIL のみ）
    if failures:
        ttk.Label(
            frame,
            text="Failed Tests:",
            font=(None, 12, "bold")
        ).pack(anchor="w")
        for name in failures:
            ttk.Label(
                frame,
                text=f" - {name}",
                foreground=_COLORS.get("FAIL"),
                font=(None, 12)
            ).pack(anchor="w", padx=10)
    else:
        ttk.Label(
            frame,
            text="All tests passed successfully!",
            foreground=_COLORS.get("PASS"),
            font=(None, 12)
        ).pack()

    # Close ボタン
    close_btn = ttk.Button(
        frame, text="Close", command=win.destroy
    )
    close_btn.pack(side=tk.BOTTOM, pady=(20, 0))


# エイリアスを設定
show_summary = show_summary_window

