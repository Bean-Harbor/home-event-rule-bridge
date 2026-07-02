from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def append(self, event: str, payload: dict[str, Any]) -> None:
        if self.path is None:
            return
        target = self.path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "event": event,
            **payload,
        }
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

