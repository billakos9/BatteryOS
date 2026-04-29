#!/usr/bin/env python3
"""Start the BatteryOS backend and frontend dev servers together.

Usage:
    python start_dev.py
    python start_dev.py --backend-port 8000 --frontend-port 5173

This script:
  1. Starts the FastAPI backend (api/server.py)
  2. Starts the Vite frontend dev server
  3. Opens your default browser to the frontend URL
  4. Keeps both running until you press Ctrl+C
  5. Cleans up both processes on exit
"""
from __future__ import annotations

import argparse
import atexit
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_python() -> str:
    candidates = [
        "/opt/homebrew/bin/python3.10",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3.12",
        "/usr/local/bin/python3.10",
        "/usr/local/bin/python3.11",
        sys.executable,
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise RuntimeError("Could not find a suitable Python 3.10+ binary.")


def find_npm() -> str:
    candidates = ["/opt/homebrew/bin/npm", "/usr/local/bin/npm", "npm"]
    for c in candidates:
        try:
            subprocess.run([c, "--version"], capture_output=True, check=True)
            return c
        except Exception:
            continue
    raise RuntimeError("Could not find npm. Is Node.js installed?")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def next_free_port(start: int, max_tries: int = 20) -> int:
    for p in range(start, start + max_tries):
        if port_free(p):
            return p
    raise RuntimeError(f"No free port found starting from {start}")


def start_backend(port: int) -> subprocess.Popen:
    python = find_python()
    cmd = [
        python, "-m", "uvicorn", "api.server:app",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--reload",
    ]
    print(f"[BACKEND ] Starting on http://127.0.0.1:{port}/")
    return subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def start_frontend(port: int) -> tuple[subprocess.Popen, int]:
    npm = find_npm()
    env = os.environ.copy()
    env["VITE_PORT"] = str(port)
    cmd = [npm, "run", "dev", "--", "--port", str(port)]
    print(f"[FRONTEND] Starting on http://127.0.0.1:{port}/")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT / "src" / "ui",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    return proc, port


def tail_process(proc: subprocess.Popen, label: str, stop_event: list[bool]) -> None:
    try:
        for line in proc.stdout:
            if stop_event[0]:
                break
            line = line.rstrip("\n")
            print(f"\r[{label:8s}] {line}")
    except Exception:
        pass


def extract_vite_url(proc: subprocess.Popen, timeout: float = 10.0) -> str | None:
    """Read Vite stdout until we find the actual URL it bound to."""
    import re
    start = time.time()
    for line in proc.stdout:
        elapsed = time.time() - start
        if elapsed > timeout:
            break
        text = line.rstrip("\n")
        print(f"\r[FRONTEND] {text}")
        m = re.search(r"Local:\s+(http://\S+)", text)
        if m:
            return m.group(1)
        m = re.search(r"➜\s+Local:\s+(http://\S+)", text)
        if m:
            return m.group(1)
    return None


def open_browser(url: str, delay: float = 2.5) -> None:
    time.sleep(delay)
    try:
        webbrowser.open(url)
        print(f"\n[BROWSER ] Opened {url}")
    except Exception:
        print(f"\n[INFO    ] Please open {url} in your browser.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start BatteryOS backend + frontend")
    parser.add_argument("--backend-port", type=int, default=8000, help="Backend API port (auto-finds next free if taken)")
    parser.add_argument("--frontend-port", type=int, default=5173, help="Frontend dev port (auto-finds next free if taken)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    # Auto-resolve port conflicts
    backend_port = next_free_port(args.backend_port) if not port_free(args.backend_port) else args.backend_port
    frontend_port = next_free_port(args.frontend_port) if not port_free(args.frontend_port) else args.frontend_port

    backend_url = f"http://127.0.0.1:{backend_port}/"
    frontend_url = f"http://127.0.0.1:{frontend_port}/"

    print("=" * 60)
    print("BatteryOS Development Starter")
    print("=" * 60)
    print(f"Backend : {backend_url}")
    print(f"Frontend: {frontend_url}")
    print("=" * 60)
    print()

    backend_proc = start_backend(backend_port)
    frontend_proc, actual_frontend_port = start_frontend(frontend_port)

    procs = [backend_proc, frontend_proc]

    def cleanup() -> None:
        print("\n[SHUTDOWN] Stopping servers...")
        for p in procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        print("[SHUTDOWN] Done.")

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda _s, _f: sys.exit(0))

    import threading
    stop_event = [False]
    bt = threading.Thread(target=tail_process, args=(backend_proc, "BACKEND ", stop_event), daemon=True)
    ft = threading.Thread(target=tail_process, args=(frontend_proc, "FRONTEND", stop_event), daemon=True)
    bt.start()
    ft.start()

    if not args.no_browser:
        browser_thread = threading.Thread(target=open_browser, args=(frontend_url,), daemon=True)
        browser_thread.start()

    print("\n[INFO    ] Press Ctrl+C to stop both servers.\n")

    try:
        while True:
            time.sleep(1)
            for p, name in zip(procs, ["backend", "frontend"]):
                if p.poll() is not None:
                    print(f"\n[ERROR   ] {name} process exited with code {p.returncode}")
                    sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event[0] = True
        cleanup()


if __name__ == "__main__":
    main()
