"""Mantiene el túnel HTTPS de localhost.run: reconecta y pinea /health para que no expire."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_URL_FILE = _ROOT / "data" / "tunnel-url.txt"
_URL_RE = re.compile(r"https://[a-z0-9]+\.lhr\.life", re.I)

_SSH = [
    "ssh",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=4",
    "-o",
    "ExitOnForwardFailure=yes",
    "-o",
    "PubkeyAuthentication=no",
    "-o",
    "PreferredAuthentications=none",
    "-R",
    "80:127.0.0.1:8000",
    "nokey@localhost.run",
]


def _save(url: str) -> None:
    _URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    _URL_FILE.write_text(url.strip() + "\n", encoding="utf-8")
    webhook = url.rstrip("/") + "/webhook"
    print(flush=True)
    print("=" * 60, flush=True)
    print("Pegá en Meta (Callback URL):", flush=True)
    print(webhook, flush=True)
    print("Token:", "iahaf-verify-cambiar", flush=True)
    print("=" * 60, flush=True)


def _heartbeat(holder: dict) -> None:
    fails = 0
    while not holder.get("stop"):
        time.sleep(90)
        url = holder.get("url") or ""
        if not url:
            continue
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=20) as resp:
                resp.read(80)
            fails = 0
            print("túnel vivo:", url, flush=True)
        except Exception as exc:
            fails += 1
            print("túnel no responde:", exc, flush=True)
            proc = holder.get("proc")
            if fails >= 2 and proc is not None and proc.poll() is None:
                print("reinicio el túnel", flush=True)
                proc.terminate()


def main() -> int:
    holder: dict = {"url": "", "proc": None, "stop": False}
    ping = threading.Thread(target=_heartbeat, args=(holder,), daemon=True)
    ping.start()
    print("Túnel IAHAF: localhost.run con ping cada 90s (Ctrl+C para parar)", flush=True)
    try:
        while True:
            proc = subprocess.Popen(
                _SSH,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            holder["proc"] = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                found = _URL_RE.search(line)
                if found:
                    url = found.group(0)
                    holder["url"] = url
                    _save(url)
            proc.wait()
            holder["proc"] = None
            print("SSH cortado; reconecto en 4s…", flush=True)
            time.sleep(4)
    except KeyboardInterrupt:
        holder["stop"] = True
        proc = holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()
        print("túnel detenido", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
