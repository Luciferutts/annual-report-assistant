"""Local desktop window for API provider setup."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import webbrowser

from openharness.auth.manager import AuthManager
from openharness.config.settings import auth_source_uses_api_key


PROJECT = Path(__file__).resolve().parents[1]


def configure_api_profile(profile_name: str, api_key: str) -> None:
    """Save a key in the selected profile's namespace and then activate it."""
    key = api_key.strip()
    if not key:
        raise ValueError("请先输入 API Key。")
    manager = AuthManager()
    profile = manager.list_profiles().get(profile_name)
    if profile is None or not auth_source_uses_api_key(profile.auth_source):
        raise ValueError("请选择使用 API Key 的模型服务。")
    manager.store_profile_credential(profile_name, "api_key", key)
    manager.use_profile(profile_name)


def show_setup_window() -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("OpenHarness · 模型配置")
    width, height = 640, 450
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(width, height)

    frame = ttk.Frame(root, padding=28)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text="连接你的模型", font=("Helvetica", 22, "bold")).grid(
        row=0, column=0, sticky="w", pady=(0, 8)
    )
    ttk.Label(frame, text="已选 DeepSeek。把 API Key 粘贴到下方输入框，再点击“保存并启动”。").grid(
        row=1, column=0, sticky="w", pady=(0, 20)
    )

    profiles = AuthManager().list_profiles()
    api_profiles = {name: profile for name, profile in profiles.items()
                    if auth_source_uses_api_key(profile.auth_source)}
    names = sorted(api_profiles, key=lambda name: (name != "deepseek", name))
    labels = {name: ("DeepSeek（深度求索）" if name == "deepseek" else api_profiles[name].label)
              for name in names}
    by_label = {label: name for name, label in labels.items()}
    selected = tk.StringVar(value=labels.get("deepseek", labels[names[0]]))
    model_text = tk.StringVar()
    key_label = tk.StringVar()
    key = tk.StringVar()
    status = tk.StringVar(value="等待输入 DeepSeek API Key")
    status_path = PROJECT / ".openharness" / "setup-window-status.json"

    def record(phase: str) -> None:
        try:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({
                "phase": phase,
                "profile": by_label[selected.get()],
            }, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    ttk.Label(frame, text="模型服务").grid(row=2, column=0, sticky="w")
    picker = ttk.Combobox(frame, textvariable=selected, values=list(by_label), state="readonly")
    picker.grid(row=3, column=0, sticky="ew", pady=(5, 8))
    ttk.Label(frame, textvariable=model_text).grid(row=4, column=0, sticky="w", pady=(0, 18))
    ttk.Label(frame, textvariable=key_label).grid(row=5, column=0, sticky="w")
    entry = ttk.Entry(frame, textvariable=key, show="•", width=60)
    entry.grid(row=6, column=0, sticky="ew", pady=(5, 8))
    reveal = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="显示密钥", variable=reveal,
                    command=lambda: entry.configure(show="" if reveal.get() else "•")).grid(
        row=7, column=0, sticky="w"
    )

    def choose_provider(_event=None) -> None:
        name = by_label[selected.get()]
        profile = api_profiles[name]
        model_text.set(f"模型：{profile.resolved_model}")
        key_label.set("DeepSeek API Key" if name == "deepseek" else f"{profile.label} API Key")
        key.set("")
        status.set(f"等待输入 {profile.label} API Key")
        record("awaiting_key")

    picker.bind("<<ComboboxSelected>>", choose_provider)

    def save_and_start() -> None:
        name = by_label[selected.get()]
        try:
            configure_api_profile(name, key.get())
        except ValueError as error:
            status.set(str(error))
            entry.focus_set()
            return
        except Exception:
            status.set("保存未成功，请检查配置目录的写入权限。")
            return
        key.set("")
        record("saved")
        try:
            subprocess.run(
                ["/usr/bin/open", "-a", "Terminal", str(PROJECT / "scripts/launch_terminal.command")],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            status.set("密钥已保存。请双击项目中的 scripts/launch_terminal.command 启动。")
            return
        record("launch_requested")
        status.set("配置已保存，请在新打开的终端窗口中使用 OpenHarness。")
        save_button.configure(state="disabled")

    save_button = ttk.Button(frame, text="保存并启动 OpenHarness", command=save_and_start)
    save_button.grid(row=8, column=0, sticky="ew", pady=(18, 10))
    ttk.Label(frame, textvariable=status, wraplength=570).grid(row=9, column=0, sticky="w")
    ttk.Button(frame, text="获取 DeepSeek API Key ↗",
               command=lambda: webbrowser.open("https://platform.deepseek.com/api_keys")).grid(
        row=10, column=0, sticky="w", pady=(14, 0)
    )
    entry.bind("<Return>", lambda _event: save_and_start())
    choose_provider()
    root.update()
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    entry.focus_set()
    root.after(2500, lambda: root.attributes("-topmost", False))
    print(f"SETUP_WINDOW_READY visible={bool(root.winfo_viewable())} provider=deepseek", flush=True)
    root.mainloop()


if __name__ == "__main__":
    show_setup_window()
