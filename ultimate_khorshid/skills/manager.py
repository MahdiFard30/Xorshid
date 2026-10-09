"""Skills — مهارت‌های Markdown (استاندارد agentskills.io مثل OpenJarvis).

هر مهارت یک پوشه با SKILL.md است:
---
name: my-skill
description: ...
---
# دستورالعمل...
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from ultimate_khorshid.core.registry import SkillRegistry


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    body: str
    path: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


def parse_skill_file(fp: Path) -> Skill | None:
    try:
        text = fp.read_text(encoding="utf-8")
    except Exception:
        return None
    meta: Dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            front = text[3:end].strip()
            body = text[end + 3:].strip()
            for line in front.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip("\"'")
    name = meta.get("name", fp.parent.name if fp.name == "SKILL.md" else fp.stem)
    return Skill(name=name, description=meta.get("description", body[:120]),
                 body=body, path=str(fp), metadata=meta)


class SkillManager:
    def __init__(self, dirs: List[str] | None = None) -> None:
        self.dirs = [Path(os.path.expanduser(d)) for d in (dirs or [])]
        builtin = Path(__file__).parent / "builtins"
        if builtin.exists():
            self.dirs.append(builtin)
        self._skills: Dict[str, Skill] = {}

    def load_all(self) -> Dict[str, Skill]:
        self._skills.clear()
        for d in self.dirs:
            if not d.exists():
                continue
            for fp in list(d.glob("*/SKILL.md")) + list(d.glob("*.md")):
                sk = parse_skill_file(fp)
                if sk and sk.name not in self._skills:
                    self._skills[sk.name] = sk
                    try:
                        SkillRegistry.register_value(sk.name, sk)
                    except ValueError:
                        pass
        return self._skills

    def get(self, name: str) -> Skill | None:
        if name in self._skills:
            return self._skills[name]
        if SkillRegistry.contains(name):
            return SkillRegistry.get(name)
        return None

    def catalog_text(self) -> str:
        if not self._skills:
            self.load_all()
        if not self._skills:
            return "(مهارتی نصب نیست)"
        return "\n".join(f"- {s.name}: {s.description[:120]}" for s in self._skills.values())

    def inject(self, names: List[str]) -> str:
        """متن مهارت‌ها برای تزریق به system prompt."""
        if not self._skills:
            self.load_all()
        parts = []
        for n in names:
            sk = self.get(n)
            if sk:
                parts.append(f"# مهارت: {sk.name}\n{sk.body[:3000]}")
        return "\n\n---\n\n".join(parts)
