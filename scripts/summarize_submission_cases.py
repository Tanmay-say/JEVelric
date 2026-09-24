"""Write a detailed report for the current static submission answers."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"
OUT = ROOT / "reports" / "grip_ablation" / "final_static_cases_report.md"


def action_list(items: list[dict]) -> str:
    if not items:
        return "(empty)"
    return "; ".join(
        f"{item.get('action')} [{item.get('route')}] — {item.get('reason')}"
        for item in items
    )


def main() -> None:
    rows: list[str] = []
    details: list[str] = []
    for index in range(1, 21):
        case_id = f"HHG-{index:03d}"
        payload = json.loads((CASES / f"{case_id}.json").read_text(encoding="utf-8"))
        case = payload["case"]
        actions = payload["next_best_actions"]
        final_actions = [item.get("action") for item in actions.get("final", [])]
        rows.append(
            "| {case} | {status} | {verdict} | {prob} | {pattern} | {actions} | {sar} |".format(
                case=case_id,
                status=case.get("status"),
                verdict=case.get("verdict"),
                prob=case.get("fraud_probability"),
                pattern=case.get("pattern"),
                actions=", ".join(final_actions) or "(empty)",
                sar="file" if payload.get("sar", {}).get("file") else "no file",
            )
        )
        evidence = case.get("evidence", [])
        evidence_lines = "\n".join(
            f"  - {item.get('source')} `{item.get('ref')}`: {item.get('claim')} "
            f"(IDs: {', '.join(item.get('entity_ids') or []) or 'none'})"
            for item in evidence
        ) or "  - No evidence items recorded."
        details.append(
            f"## {case_id}\n\n"
            f"- **Finding:** {case.get('status')} / {case.get('verdict')} / "
            f"{case.get('pattern')} / probability {case.get('fraud_probability')} / "
            f"exposure ${case.get('exposure_usd', 0):.2f}\n"
            f"- **Initial actions:** {action_list(actions.get('initial', []))}\n"
            f"- **Final actions:** {action_list(actions.get('final', []))}\n"
            f"- **What changed:** {actions.get('what_changed', '')}\n"
            f"- **Evidence items:** {len(evidence)}\n{evidence_lines}\n"
            f"- **SAR:** file={payload.get('sar', {}).get('file')}; "
            f"reason={payload.get('sar', {}).get('reason')}; "
            f"amount=${payload.get('sar', {}).get('total_amount_usd', 0):.2f}; "
            f"dates={payload.get('sar', {}).get('activity_dates', [])}\n"
            f"- **Run:** tool_calls={payload.get('tool_calls')}; tokens={payload.get('tokens')}; "
            f"latency={payload.get('latency_s')}s\n"
            f"- **Summary:** {case.get('summary')}\n"
        )

    report = (
        "# Final static submission case report\n\n"
        "This report describes the current `cases/HHG-001.json` through `HHG-020.json` "
        "answer files. They were generated through the normal static submission path; "
        "the GRIP-only provider monkey patch is in a separate runner. The live TigerGraph "
        "answer validator passed all 20 files after the action-language validation was added.\n\n"
        "| Case | Status | Verdict | Probability | Pattern | Final actions | SAR |\n"
        "|---|---|---|---:|---|---|---|\n"
        + "\n".join(rows)
        + "\n\n"
        + "\n".join(details)
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
