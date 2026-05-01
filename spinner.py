import sys
import threading
import time

_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_WIDTH  = 60


class Spinner:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._message = ""
        self._lock = threading.Lock()

    def start(self, message: str = "") -> None:
        self._stop.clear()
        with self._lock:
            self._message = message
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        with self._lock:
            self._message = message

    def stop(self, final: str = "") -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        sys.stdout.write(f"\r{' ' * _WIDTH}\r")
        sys.stdout.flush()
        if final:
            print(final)

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            with self._lock:
                msg = self._message
            frame = _FRAMES[i % len(_FRAMES)]
            line = f"  {frame}  {msg}"
            sys.stdout.write(f"\r{line:<{_WIDTH}}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
