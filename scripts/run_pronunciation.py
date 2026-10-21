"""Start the CET web app and the isolated local analysis worker without printing configuration."""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8001)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    worker_python = (
        root / ".speech-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    if not worker_python.exists():
        raise SystemExit("Create .speech-venv and install speech_service/requirements.txt first.")
    for port in (args.port, args.worker_port):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(
                    f"Port {port} is already in use. Select another port; existing services were not stopped."
                )
    env = dict(os.environ, SPEAKING_SERVICE_URL=f"http://127.0.0.1:{args.worker_port}")
    children = []
    exit_code = 0
    try:
        children.append(
            subprocess.Popen(
                [
                    str(worker_python),
                    "-m",
                    "uvicorn",
                    "speech_service.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.worker_port),
                ],
                cwd=root,
                env=env,
            )
        )
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                cwd=root,
                env=env,
            )
        )
        print(
            f"English pronunciation: http://127.0.0.1:{args.port}/vocab/#/pronunciation", flush=True
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        exit_code = 1
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
