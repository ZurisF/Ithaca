"""Create a local .env with a fresh shared desktop token."""

from pathlib import Path
from secrets import token_urlsafe

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    raise SystemExit(".env already exists; keeping the existing local configuration")
template = (root / ".env.example").read_text(encoding="utf-8")
token = token_urlsafe(48)
template = template.replace("replace-with-random-local-token", token)
destination.write_text(template, encoding="utf-8")
destination.chmod(0o600)
print("Created .env with a new local desktop token")
