import argparse
import logging
import socket
import threading
import time
import webbrowser

import uvicorn


def open_browser_when_up(host: str, port: int, timeout_s: float = 30.0) -> None:
    """Open the UI in the default browser once the server accepts connections."""
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.3)
    else:
        return
    webbrowser.open(f"http://{connect_host}:{port}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Home trainer app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    ap.add_argument(
        "--no-browser", action="store_true", help="do not open the UI in the browser at start"
    )
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not (args.no_browser or args.reload):
        threading.Thread(
            target=open_browser_when_up, args=(args.host, args.port), daemon=True
        ).start()
    uvicorn.run(
        "hometrainer.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
