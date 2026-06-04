import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "packages" / "core"))

from fastapi.testclient import TestClient

from app.gateway.app import app
from nexagent.models.factory import REASONING_MODES, get_model_capabilities


def main() -> int:
    assert set(REASONING_MODES) == {"fast", "balanced", "deep", "ultra"}
    caps = get_model_capabilities("openai", "gpt-5")
    assert "ultra" in caps["supported_reasoning_modes"]
    basic = get_model_capabilities("openai", "qwen2.5-7b")
    assert basic["supported_reasoning_modes"] == ["fast", "balanced", "deep", "ultra"]
    with TestClient(app) as client:
        models = client.get("/api/models")
        assert models.status_code == 200, models.text
        assert "reasoning_modes" in models.json()
    print("Reasoning mode verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
