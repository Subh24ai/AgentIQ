#!/usr/bin/env python3
"""Create a local .env from .env.example with a freshly generated JWT_SECRET.

Run from the project root:

    python3 scripts/generate_env.py

Refuses to overwrite an existing .env so a configured secret is never clobbered.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"


def main() -> int:
    if ENV_FILE.exists():
        print(f"⚠ {ENV_FILE} already exists — refusing to overwrite it.")
        print("  Delete it first if you really want a fresh .env.")
        return 1

    if not ENV_EXAMPLE.exists():
        print(f"✗ {ENV_EXAMPLE} not found — run this from the project root.")
        return 1

    secret = secrets.token_hex(32)
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(keepends=True)

    replaced = False
    out: list[str] = []
    for line in lines:
        # Substitute the JWT_SECRET assignment (anything after `JWT_SECRET=`,
        # including the placeholder comment), preserving the trailing newline.
        if re.match(r"\s*JWT_SECRET\s*=", line) and not replaced:
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"JWT_SECRET={secret}{newline}")
            replaced = True
        else:
            out.append(line)

    if not replaced:
        # No JWT_SECRET line in the template — append one so the result is usable.
        out.append(f"\nJWT_SECRET={secret}\n")

    ENV_FILE.write_text("".join(out), encoding="utf-8")
    print("✓ .env created. Fill in your API keys then run: docker compose up --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
