import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "packages" / "core"))

from fastapi.testclient import TestClient

from app.gateway.app import app


def main() -> int:
    with TestClient(app) as client:
        for kind in ("agent", "skill", "mcp"):
            draft = client.post(f"/api/creator/{kind}/draft", json={"goal": f"verify {kind}"})
            assert draft.status_code == 200, draft.text
            assert draft.json()["draft"]

        skill_draft = client.post("/api/creator/skill/draft", json={"goal": "verify creator skill"}).json()["draft"]
        skill_draft["id"] = "verify-creator-skill"
        saved = client.post("/api/creator/skill/save", json={"draft": skill_draft})
        assert saved.status_code in {201, 409}, saved.text
        client.delete("/api/skills/verify-creator-skill")
    print("Creator verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
