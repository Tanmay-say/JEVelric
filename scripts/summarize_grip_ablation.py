"""Build a case-by-case Markdown report from saved GRIP benchmark answers."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "grip_ablation"
BASELINE = REPORT_DIR / "static_baseline"
GRIP = REPORT_DIR / "grip_cases"
CONTROLS = REPORT_DIR / "static_control"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def actions(data: dict) -> str:
    return ", ".join(item.get("action", "") for item in data.get("next_best_actions", {}).get("final", [])) or "(empty)"


def evidence_ids(data: dict) -> set[str]:
    result: set[str] = set()
    for item in data.get("case", {}).get("evidence", []):
        result.update(str(value) for value in item.get("entity_ids", []))
    result.update(str(value) for value in data.get("case", {}).get("affected_txn_ids", []))
    result.update(str(value) for value in data.get("case", {}).get("connected_card_ids", []))
    result.update(str(value) for value in data.get("case", {}).get("similar_prior_cases", []))
    return result


def fields(data: dict) -> str:
    case = data["case"]
    return " / ".join(
        (
            str(case.get("status", "")),
            str(case.get("verdict", "")),
            str(case.get("pattern", "")),
            f"p={case.get('fraud_probability', '')}",
            actions(data),
        )
    )


def main() -> None:
    rows: list[str] = []
    for index in range(1, 21):
        case_id = f"HHG-{index:03d}"
        baseline = load(BASELINE / f"{case_id}.json")
        grip = load(GRIP / f"{case_id}.json")
        control_path = CONTROLS / f"{case_id}.json"
        control = load(control_path) if control_path.exists() else None
        base_ids = evidence_ids(baseline)
        grip_ids = evidence_ids(grip)
        only_grip = sorted(grip_ids - base_ids)
        only_base = sorted(base_ids - grip_ids)
        latency = grip.get("latency_s", "")
        tokens = grip.get("tokens", "")
        rows.append(
            "| {case} | {base} | {control} | {grip} | {evidence} | {tokens} | {latency}s |".format(
                case=case_id,
                base=fields(baseline),
                control=fields(control) if control else "(not run)",
                grip=fields(grip),
                evidence=(
                    f"{len(base_ids)} static / {len(grip_ids)} GRIP; "
                    f"GRIP-only: {', '.join(only_grip[:8]) or 'none'}"
                    f"{' …' if len(only_grip) > 8 else ''}; "
                    f"static-only: {', '.join(only_base[:8]) or 'none'}"
                    f"{' …' if len(only_base) > 8 else ''}"
                ),
                tokens=tokens,
                latency=latency,
            )
        )

    report = """# GRIP A/B case comparison

Generated from saved case answer files. Static baseline is the archived run; current static controls are same-session controls where present. Provider/run drift is visible in several archived comparisons, so GRIP-specific conclusions use same-session controls when available.

## Graph connection verification

The saved pre-benchmark snapshot `phase1_raw_tools.json` is a real TigerGraph response, not the demo backend. Its status was `backend=tigergraph`, `graph_id=HHGOA`, version `release_4.2.5_08-26-2026`, with 633,412 vertices and 1,758,428 edges. It was captured on 2026-09-24 at 23:34:57 local time; there is no status probe timestamped immediately before the benchmark began.

A live post-benchmark probe is in `live_status_after_benchmark.json`: it again identifies TigerGraph/HHGOA, with 648,353 vertices, 1,786,304 edges, and the augmented 12-vertex / 15-edge topology (original 8/13 plus GRIP's four vertex and two edge types). The GRIP launcher constructs `TigerGraphAdapter`, checks health, and fails closed unless it returns `status=ok` for HHGOA. Retrieval also rejects keyword-only fallback unless `query.note=vector` and a corpus entity is returned. The adapter path contains no demo fallback.

Per-case answer JSON does not persist each GRIP retrieval response. `assemble_context` falls back to static context if a GRIP tool errors, so the saved answers cannot prove case by case that every hybrid call succeeded. Treat outcome deltas as exploratory; the configured endpoint itself was not the demo backend.

## Validation after action-consistency fix

The current static submission files in `cases/` passed live validation 20/20 after the fix: answer schema, graph-known IDs, graph-write markers, action-language check, and live Transaction count (590,742). Repository-wide pytest passed 24 tests. The historical GRIP files predate the fix; the new audit flags HHG-004, HHG-014, and HHG-016 in those files. The current submission set has zero such mismatches.

The answer files do not record provider identity per model call. The later experiment segment used the isolated Groq → NVIDIA NIM → Cloudflare runner; the current static submission path is `scripts/run_cases_groq.py` (Groq → OpenRouter). Earlier GRIP cases predate the ablation-chain change. Do not interpret token/latency changes as vector-only effects.

| Case | Archived static (status / verdict / pattern / p / actions) | Same-session static | GRIP | Evidence ID counts and delta | GRIP tokens | GRIP latency |
|---|---|---|---|---|---:|---:|
""" + "\n".join(rows) + "\n\n## Review findings\n\n- Static remains the default because the comparison is mixed and some pattern changes are GRIP-specific.\n- The summary/policy mismatch was fixed at its source. The current `cases/` set has no empty-action/action-language mismatches; the historical GRIP experiment outputs preserve three such cases (HHG-004, HHG-014, HHG-016) from before the fix.\n- HHG-019 is a same-session GRIP-specific pattern difference (`account_takeover` vs `card_not_present_new_device`) while status, verdict, and actions agree.\n- HHG-004 also changed materially under GRIP versus its same-session static control (closed_fraud / fraud / 0.82 vs open / uncertain / 0.68). Keep this flagged for analyst review; do not promote GRIP based on the current sample.\n"
    (REPORT_DIR / "comparison_report.md").write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT_DIR / 'comparison_report.md'}")


if __name__ == "__main__":
    main()
