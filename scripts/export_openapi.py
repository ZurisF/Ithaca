"""Write the FastAPI contract consumed by the generated Web client."""

import json
from pathlib import Path

from app.main import app

destination = Path(__file__).resolve().parents[1] / "packages/api_contract/openapi.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"Wrote {destination.relative_to(Path(__file__).resolve().parents[1])}")
