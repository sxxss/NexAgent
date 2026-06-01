import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "packages" / "core"))

from fastapi.testclient import TestClient

from app.gateway.app import app


def main() -> int:
    with TestClient(app) as client:
        mcp = client.post(
            "/api/mcp/custom",
            json={"id": "verify-mcp", "name": "Verify MCP", "transport": "stdio", "command": ["node", "--version"]},
        )
        assert mcp.status_code in {201, 409}, mcp.text
        test_mcp = client.post("/api/mcp/verify-mcp/test")
        assert test_mcp.status_code == 200, test_mcp.text
        client.delete("/api/mcp/verify-mcp")

        skill = client.post(
            "/api/skills/custom",
            json={"id": "verify-skill", "name": "Verify Skill", "description": "smoke", "content": "Use for smoke tests."},
        )
        assert skill.status_code in {201, 409}, skill.text
        test_skill = client.post("/api/skills/verify-skill/test")
        assert test_skill.status_code == 200, test_skill.text
        client.delete("/api/skills/verify-skill")
    print("Custom MCP/Skill verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
