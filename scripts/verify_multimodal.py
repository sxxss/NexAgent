import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "packages" / "core"))

from fastapi.testclient import TestClient

from app.gateway.app import app


def main() -> int:
    with TestClient(app) as client:
        upload = client.post(
            "/api/media/analyze-image",
            files={"file": ("smoke.png", b"abc", "image/png")},
        )
        assert upload.status_code == 200, upload.text
        assert "artifact" in upload.json()
        rejected = client.post("/api/media/generate-image", json={"prompt": "smoke", "model": "unknown"})
        assert rejected.status_code == 400, rejected.text
    print("Multimodal verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
