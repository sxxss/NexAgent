import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "packages" / "core"))

from fastapi.testclient import TestClient

from app.gateway.app import app


def main() -> int:
    with TestClient(app) as client:
        created = client.post("/api/conversations/", json={"title": "Smoke", "agent_id": "chatbot", "agent_name": "Chat"})
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        fetched = client.get(f"/api/conversations/{cid}")
        assert fetched.status_code == 200, fetched.text
        renamed = client.patch(f"/api/conversations/{cid}", json={"title": "Smoke Renamed"})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["title"] == "Smoke Renamed"
        deleted = client.delete(f"/api/conversations/{cid}")
        assert deleted.status_code == 204, deleted.text
    print("Conversation verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
