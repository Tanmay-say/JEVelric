"""Report answer files whose action prose conflicts with an empty final list."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validate import _ACTION_LIKE_TEXT  # noqa: E402

DIRECTORIES = (
    ROOT / "cases",
    ROOT / "reports" / "grip_ablation" / "static_baseline",
    ROOT / "reports" / "grip_ablation" / "static_control",
    ROOT / "reports" / "grip_ablation" / "grip_cases",
)


def main() -> None:
    total = 0
    for directory in DIRECTORIES:
        findings: list[str] = []
        if not directory.exists():
            continue
        for path in sorted(directory.glob("HHG-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("case_id") not in {f"HHG-{i:03d}" for i in range(1, 21)}:
                continue
            actions = (payload.get("next_best_actions") or {}).get("final") or []
            if actions:
                continue
            case = payload.get("case") or {}
            text = f"{case.get('summary', '')}\n{(payload.get('sar') or {}).get('narrative', '')}"
            if _ACTION_LIKE_TEXT.search(text):
                findings.append(path.stem)
        total += len(findings)
        print(f"{directory.relative_to(ROOT)}: {len(findings)} cases: {', '.join(findings) or 'none'}")
    print(f"Total findings across directories (not de-duplicated): {total}")


if __name__ == "__main__":
    main()
