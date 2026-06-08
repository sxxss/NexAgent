from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_virtual_path_translator_keeps_paths_inside_thread():
    from nexagent.sandbox import VirtualPathTranslator

    base_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "sandbox"
    base_dir.mkdir(parents=True, exist_ok=True)
    translator = VirtualPathTranslator(base_dir)
    real = translator.to_real("/mnt/user-data/workspace/report.md", "thread-1")

    assert real == (base_dir / "threads" / "thread-1" / "workspace" / "report.md").resolve()
    assert translator.to_virtual(real, "thread-1") == "/mnt/user-data/workspace/report.md"

    skill_real = translator.to_real("/mnt/skills/demo/SKILL.md", "thread-1")
    assert skill_real == (base_dir / "threads" / "thread-1" / "skills" / "demo" / "SKILL.md").resolve()
    assert translator.to_virtual(skill_real, "thread-1") == "/mnt/skills/demo/SKILL.md"

    custom_skill_real = translator.to_real("/mnt/skills/custom/demo/SKILL.md", "thread-1")
    assert custom_skill_real == (
        base_dir / "threads" / "thread-1" / "skills" / "custom" / "demo" / "SKILL.md"
    ).resolve()
    assert translator.to_virtual(custom_skill_real, "thread-1") == "/mnt/skills/custom/demo/SKILL.md"


@pytest.mark.unit
def test_virtual_path_translator_rejects_escape():
    from nexagent.sandbox import VirtualPathTranslator

    base_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "sandbox"
    base_dir.mkdir(parents=True, exist_ok=True)
    translator = VirtualPathTranslator(base_dir)

    with pytest.raises(ValueError):
        translator.to_real("/mnt/user-data/workspace/../../secret.txt", "thread-1")
