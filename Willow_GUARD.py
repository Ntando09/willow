"""Willow Guardian — health monitor, backup restore, process launcher."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import urllib.request
except ImportError:
    urllib = None  # type: ignore

ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / "backups"
LOG_FILE = ROOT / "guard.log"
HEALTH_URL = "http://localhost:8000/health"
PING_INTERVAL = 2
FAIL_THRESHOLD = 6  # seconds without response

processes: list[subprocess.Popen] = []
running = True


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def ping_health() -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_latest_backup(pattern: str) -> Path | None:
    if not BACKUP_DIR.exists():
        return None
    matches = sorted(BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def restore_backups() -> None:
    """Restore latest backups for critical files."""
    log("Attempting backup restore...")
    mappings = {
        "backend_main.py_*.bak": ROOT / "backend" / "main.py",
        "src_app_page.tsx_*.bak": ROOT / "src" / "app" / "page.tsx",
    }
    restored = 0
    for pattern, target in mappings.items():
        backup = find_latest_backup(pattern)
        if backup and target.parent.exists():
            shutil.copy2(backup, target)
            log(f"Restored {target} from {backup.name}")
            restored += 1
    if restored == 0:
        log("No backups found to restore")


def kill_processes() -> None:
    global processes
    for proc in processes:
        if proc.poll() is None:
            try:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    processes = []


def start_services() -> None:
    global processes
    kill_processes()
    log("Starting Willow services...")

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]

    frontend = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    processes.append(frontend)
    log(f"Frontend started (pid {frontend.pid}) on port 3000")

    backend = subprocess.Popen(
        uvicorn_cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    processes.append(backend)
    log(f"Backend started (pid {backend.pid}) on port 8000")


def handle_shutdown(signum: int, frame: object) -> None:
    global running
    log(f"Shutdown signal received ({signum})")
    running = False
    kill_processes()
    sys.exit(0)


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    log("Willow Guardian v10.4 starting")
    log(f"Root: {ROOT}")

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
    else:
        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

    start_services()

    # Wait for backend to come up
    for _ in range(15):
        if ping_health():
            log("Backend health OK")
            break
        time.sleep(1)
    else:
        log("Backend not healthy yet — will keep monitoring")

    last_ok = time.time()
    fail_start: float | None = None

    while running:
        time.sleep(PING_INTERVAL)
        if ping_health():
            last_ok = time.time()
            fail_start = None
            continue

        if fail_start is None:
            fail_start = time.time()
            log("Health check failed — starting watchdog timer")

        elapsed = time.time() - fail_start
        if elapsed >= FAIL_THRESHOLD:
            log(f"No health response for {elapsed:.0f}s — restoring and restarting")
            restore_backups()
            start_services()
            last_ok = time.time()
            fail_start = None

            for _ in range(15):
                if ping_health():
                    log("Recovery successful")
                    break
                time.sleep(1)
            else:
                log("Recovery attempted but backend still unhealthy")


if __name__ == "__main__":
    main()
