#!/usr/bin/env python3
"""Start the read-only page. Reads .env itself so the shell never sees the password."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv" / "bin" / "python"


def load_env(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def main():
    if VENV.exists() and Path(sys.prefix).resolve() != VENV.parent.parent.resolve():
        os.execv(VENV, [str(VENV), str(Path(__file__).resolve()), *sys.argv[1:]])

    os.chdir(ROOT)
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit("missing .env (see .env.example)")
    load_env(env_path)
    os.environ.setdefault("POSTGRES_SSLMODE", "require")

    import uvicorn

    port = int(os.environ.get("WEB_PORT", "8000"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
