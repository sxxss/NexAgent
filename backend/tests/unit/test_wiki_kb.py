from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


def _work_dir(prefix: str) -> Path:
    path = Path("test-artifacts") / "wiki-kb" / prefix / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_kb_can_be_created_and_discovered_by_manager():
    from nexagent.knowledge.manager import reset_manager
    from nexagent.knowledge.models import KBType

    work_dir = _work_dir("create")
    try:
        manager = reset_manager(str(work_dir))

        kb = await manager.create_kb(name="LLM Wiki", description="Project memory", kb_type="wiki")
        loaded = manager.get_kb(kb.kb_id)
        all_kbs = manager.list_kbs()

        assert kb.kb_type == KBType.WIKI
        assert loaded is not None
        assert loaded.kb_id == kb.kb_id
        assert any(item.kb_id == kb.kb_id for item in all_kbs)
        assert (work_dir / "wiki" / kb.kb_id / "wiki" / "sources").exists()
        assert (work_dir / "wiki" / kb.kb_id / "purpose.md").read_text(
            encoding="utf-8"
        ).startswith("# LLM Wiki")
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
