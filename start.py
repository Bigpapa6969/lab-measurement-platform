"""
start.py — Launch backend + frontend with a single command
==========================================================
Run from the project root:

    python start.py

Starts:
  - FastAPI backend  on http://localhost:8000
  - Vite/React frontend on http://localhost:5173

Press Ctrl+C to stop both.
"""
import subprocess
import sys
import os
import signal
import time
from pathlib import Path

ROOT    = Path(__file__).parent
BACKEND  = ROOT / "backend"
FRONTEND = ROOT / "frontend"

BACKEND_CMD  = [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"]
FRONTEND_CMD = ["npm", "run", "dev"]

# On Windows, npm is a .cmd file so we need shell=True
IS_WIN = sys.platform == "win32"


def main():
    print("Starting Lab Measurement Platform...")
    print(f"  Backend  → http://localhost:8000")
    print(f"  Frontend → http://localhost:5173")
    print("  Press Ctrl+C to stop both.\n")

    backend = subprocess.Popen(
        BACKEND_CMD,
        cwd=BACKEND,
        # Forward output directly to this terminal
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    frontend = subprocess.Popen(
        FRONTEND_CMD,
        cwd=FRONTEND,
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=IS_WIN,   # required on Windows for npm.cmd
    )

    def shutdown(sig=None, frame=None):
        print("\nShutting down...")
        frontend.terminate()
        backend.terminate()
        # Give them a moment to exit cleanly
        time.sleep(1)
        frontend.kill()
        backend.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Wait — if either process dies unexpectedly, kill the other and exit
    while True:
        ret_b = backend.poll()
        ret_f = frontend.poll()

        if ret_b is not None:
            print(f"\nBackend exited unexpectedly (code {ret_b}). Stopping frontend.")
            frontend.terminate()
            sys.exit(ret_b)

        if ret_f is not None:
            print(f"\nFrontend exited unexpectedly (code {ret_f}). Stopping backend.")
            backend.terminate()
            sys.exit(ret_f)

        time.sleep(1)


if __name__ == "__main__":
    main()
