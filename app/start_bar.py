import json
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_USER_PATH = _REPO_ROOT / "config.user.json"
CONFIG_DEFAULT_PATH = _REPO_ROOT / "config.default.json"
CONFIG_LEGACY_PATH = _REPO_ROOT / "config.json"
REQ_FILE = _REPO_ROOT / "requirements.txt"

# Pulled on first-run wizard (same image serves translation + AI Vision OCR on Docker Model Runner)
SETUP_DOCKER_MODEL = "docker.io/ai/gemma4:E2B"

BG = "#1a1a1a"
BG2 = "#242424"
BG3 = "#2e2e2e"
ACCENT = "#00e6ff"
TEXT = "#ffffff"
DIM = "#888888"
OK_COLOR = "#00cc6a"
ERR_COLOR = "#ff4d4d"
WARN_COLOR = "#ffaa33"
PENDING_COLOR = "#555555"

_STEPS = [
    ("packages", "Install Python packages"),
    ("model_trans", "Pull Docker model  (gemma4:E2B — translate + OCR)"),
    ("ready", "Ready to launch"),
]


def _load_effective_config() -> dict:
    """Same resolution order as app.main.load_config — first existing file wins."""
    for path in (CONFIG_USER_PATH, CONFIG_DEFAULT_PATH, CONFIG_LEGACY_PATH):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


def is_first_run() -> bool:
    try:
        return not _load_effective_config().get("setup_done", False)
    except Exception:
        return True


def mark_setup_done() -> None:
    """Persist setup_done on config.user.json (full copy if wizard ran against default only)."""
    try:
        cfg = _load_effective_config()
        cfg["setup_done"] = True
        with open(CONFIG_USER_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[setup] Could not update config.user.json: {exc}")


class StartBar:
    """First-run setup wizard — installs pip packages and pulls Docker models."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Manga Translator")
        self.root.resizable(False, False)
        self.root.config(bg=BG)
        self.root.attributes("-topmost", True)

        w, h = 500, 540
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        self._launch_requested = False
        self._setup_done = False
        self._build_ui()
        self.root.after(200, self._start_setup)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── header ──
        hdr = tk.Frame(self.root, bg=BG, pady=22)
        hdr.pack(fill=tk.X, padx=28)
        tk.Label(hdr, text="Manga Translator", font=("Segoe UI", 20, "bold"),
                 fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(hdr, text="First-time setup  ·  runs only once",
                 font=("Segoe UI", 9), fg=DIM, bg=BG).pack(anchor="w", pady=(2, 0))

        tk.Frame(self.root, bg="#2e2e2e", height=1).pack(fill=tk.X, padx=28)

        # ── step rows ──
        steps_frame = tk.Frame(self.root, bg=BG, pady=14)
        steps_frame.pack(fill=tk.X, padx=28)
        self._step_icons: dict[str, tk.Label] = {}
        self._step_labels: dict[str, tk.Label] = {}
        for key, label in _STEPS:
            row = tk.Frame(steps_frame, bg=BG, pady=6)
            row.pack(fill=tk.X)
            icon = tk.Label(row, text="○", font=("Segoe UI", 13),
                            fg=PENDING_COLOR, bg=BG, width=2, anchor="w")
            icon.pack(side=tk.LEFT)
            lbl = tk.Label(row, text=label, font=("Segoe UI", 10),
                           fg=DIM, bg=BG, anchor="w")
            lbl.pack(side=tk.LEFT, padx=(8, 0))
            self._step_icons[key] = icon
            self._step_labels[key] = lbl

        tk.Frame(self.root, bg="#2e2e2e", height=1).pack(fill=tk.X, padx=28, pady=(6, 0))

        # ── log ──
        log_frame = tk.Frame(self.root, bg=BG, pady=12)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=28)
        self._log = tk.Text(
            log_frame,
            height=11,
            bg=BG2,
            fg="#999999",
            insertbackground=TEXT,
            font=("Consolas", 8),
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#333",
            padx=8,
            pady=6,
        )
        self._log.pack(fill=tk.BOTH, expand=True)

        # ── bottom bar ──
        bottom = tk.Frame(self.root, bg=BG3, pady=14)
        bottom.pack(fill=tk.X, padx=0, side=tk.BOTTOM)
        inner = tk.Frame(bottom, bg=BG3)
        inner.pack(fill=tk.X, padx=28)

        self._status_lbl = tk.Label(inner, text="Starting setup…",
                                    font=("Segoe UI", 9), fg=DIM, bg=BG3)
        self._status_lbl.pack(side=tk.LEFT)

        self._launch_btn = tk.Button(
            inner,
            text="  Launch App  ",
            font=("Segoe UI", 10, "bold"),
            fg=BG,
            bg=ACCENT,
            activebackground="#00c8e0",
            activeforeground=BG,
            relief=tk.FLAT,
            padx=14,
            pady=7,
            cursor="hand2",
            state=tk.DISABLED,
            command=self._launch,
        )
        self._launch_btn.pack(side=tk.RIGHT)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _log_line(self, text: str):
        def _do():
            self._log.config(state=tk.NORMAL)
            self._log.insert(tk.END, text + "\n")
            self._log.see(tk.END)
            self._log.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _set_step(self, key: str, state: str):
        _map = {
            "pending": ("○", PENDING_COLOR, DIM),
            "busy":    ("◎", ACCENT,        TEXT),
            "ok":      ("✓", OK_COLOR,      TEXT),
            "warn":    ("!", WARN_COLOR,     WARN_COLOR),
            "error":   ("✗", ERR_COLOR,      ERR_COLOR),
        }
        icon_ch, icon_fg, lbl_fg = _map.get(state, _map["pending"])
        def _do():
            self._step_icons[key].config(text=icon_ch, fg=icon_fg)
            self._step_labels[key].config(fg=lbl_fg)
        self.root.after(0, _do)

    def _set_status(self, text: str, color: str = DIM):
        self.root.after(0, lambda: self._status_lbl.config(text=text, fg=color))

    # ── setup logic ─────────────────────────────────────────────────────────

    def _start_setup(self):
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self):
        # ── 1. pip packages ──────────────────────────────────────────────
        self._set_step("packages", "busy")
        self._set_status("Installing Python packages…")
        self._log_line("▸ pip install -r requirements.txt")
        pip_ok = self._run_cmd(
            [sys.executable, "-m", "pip", "install", "-r", str(REQ_FILE), "--quiet"],
            label="pip",
        )
        if pip_ok:
            self._set_step("packages", "ok")
            self._log_line("  ✓ packages up to date\n")
        else:
            self._set_step("packages", "error")
            self._log_line("  ✗ pip failed — run manually:  pip install -r requirements.txt\n")

        # ── 2. Docker model ──────────────────────────────────────────────
        self._set_step("model_trans", "busy")
        self._set_status("Pulling Docker model (translate + vision OCR)…")
        self._log_line(f"▸ docker model pull {SETUP_DOCKER_MODEL}")
        docker_ok = self._run_cmd(
            ["docker", "model", "pull", SETUP_DOCKER_MODEL],
            label="docker",
        )
        if docker_ok:
            self._set_step("model_trans", "ok")
            self._log_line("  ✓ model ready\n")
        else:
            self._set_step("model_trans", "warn")
            self._log_line(
                "  ! Could not pull model — Docker Model Runner may not be running.\n"
                "    You can still launch the app (OCR will work; translation needs Docker).\n"
            )

        # ── done ─────────────────────────────────────────────────────────
        self._set_step("ready", "ok")
        mark_setup_done()
        self._setup_done = True
        self._set_status("Setup complete — ready to launch!", OK_COLOR)
        self._log_line("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self._log_line("  Setup complete.  Click  Launch App  to start.")
        self.root.after(0, lambda: self._launch_btn.config(state=tk.NORMAL))

    def _run_cmd(self, cmd: list, label: str) -> bool:
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=flags,
            )
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self._log_line(f"    {line}")
            proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            self._log_line(f"    [{label}] not found: {cmd[0]}")
            return False
        except Exception as exc:
            self._log_line(f"    [{label}] error: {exc}")
            return False

    # ── actions ─────────────────────────────────────────────────────────────

    def _launch(self):
        self._launch_requested = True
        self.root.destroy()

    def _on_close(self):
        self.root.destroy()

    def run(self) -> bool:
        """Show the wizard; return True if the user clicked Launch App."""
        self.root.mainloop()
        return self._launch_requested
