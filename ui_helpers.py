import tkinter as tk


def create_burnin_popup(root):
    popup = tk.Toplevel(root)
    popup.title("Burn-in Test Progress")
    popup.geometry("600x400")
    txt = tk.Text(popup, height=20, width=70)
    txt.pack(padx=10, pady=10)
    return popup, txt


def create_net_popup(root):
    popup = tk.Toplevel(root)
    popup.title("Network Test Progress")
    popup.geometry("400x300")
    txt = tk.Text(popup, height=15, width=50)
    txt.pack(padx=10, pady=10)
    return popup, txt
