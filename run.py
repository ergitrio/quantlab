"""Start Quant Desk: python run.py  (add --demo for offline synthetic data)."""
import os
import socket
import sys
import time
import webbrowser
from threading import Thread

if "--demo" in sys.argv:
    os.environ["QUANT_DATA"] = "demo"
PORT = int(os.environ.get("PORT", 8000))

# Check imports first so a missing library gives a clear message instead of a dead browser tab.
missing = []
for mod in ("fastapi", "uvicorn", "pandas", "numpy", "scipy", "httpx", "yfinance", "anthropic"):
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print("\n[Quant Desk] Library belum ter-install:", ", ".join(missing))
    print("Jalankan dulu:  python -m pip install -r requirements.txt\n")
    sys.exit(1)


def open_when_ready():
    """Open the browser only once the server actually accepts connections."""
    for _ in range(120):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                print(f"\n[Quant Desk] Siap! Buka http://localhost:{PORT}\n")
                webbrowser.open(f"http://localhost:{PORT}")
                return
        except OSError:
            time.sleep(0.5)
    print("[Quant Desk] Server belum siap setelah 60 detik. Lihat pesan error di atas.")


if __name__ == "__main__":
    import uvicorn

    print("[Quant Desk] Menyalakan server... (biarkan jendela terminal ini tetap terbuka)")
    Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("web.server:app", host="127.0.0.1", port=PORT)
