"""Run one TigerGraph-backed case with optional GRIP, preserving static outputs."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config

case_id = sys.argv[1] if len(sys.argv) > 1 else "HHG-017"
mode = sys.argv[2] if len(sys.argv) > 2 else "grip"
if mode not in {"grip", "static"}:
    raise SystemExit("mode must be grip or static")
config.GRAPH_BACKEND = "tigergraph"
config.GRAPHRAG_MODE = mode
output_name = "grip_cases" if mode == "grip" else "static_control"
config.ANSWERS_DIR = ROOT / "reports" / "grip_ablation" / output_name

from src import main as app  # noqa: E402

app.ANSWERS_DIR = config.ANSWERS_DIR
rows = [row for row in app.load_case_pack() if row["case_id"] == case_id]
if not rows:
    raise SystemExit(f"No case {case_id} in case_pack.csv")

graph = app.build_graph()
try:
    app.run_case(rows[0], graph)
finally:
    from src.config import get_grip_client, get_mcp_client

    getters = [get_mcp_client] + ([get_grip_client] if mode == "grip" else [])
    for getter in getters:
        try:
            getter().close()
        except Exception:
            pass
        getter.cache_clear()
