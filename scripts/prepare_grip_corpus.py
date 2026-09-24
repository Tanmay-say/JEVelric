"""Prepare only policy, documented patterns, and closed-case text for GRIP.

Transactions are intentionally excluded. One Paper record is produced for
each closed case; longer policy/pattern files are split into bounded passages.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from mcp_server.contracts.construction import extract_concepts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "grip_corpus" / "documents.jsonl"
MAX_CHARS = 1500
MAX_CASE_CHARS = 1500
OVERLAP_CHARS = 160


def split_text(text: str) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + MAX_CHARS // 2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - OVERLAP_CHARS)
    return chunks


def paper(doc_id: str, title: str, body: str, collection: str) -> dict:
    return {
        "id": doc_id,
        "title": title,
        "abstract": body,
        "categories": [collection],
        "source_doc": collection,
    }


def build() -> tuple[list[dict], dict]:
    documents: list[dict] = []
    counts = Counter()

    for collection, path in (
        ("policy", ROOT / "policy" / "fraud_policy.md"),
        ("patterns", ROOT / "policy" / "fraud_patterns.md"),
    ):
        source = path.read_text(encoding="utf-8")
        chunks = split_text(source)
        counts[f"{collection}_source_documents"] = 1
        counts[f"{collection}_chunks"] = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            doc_id = f"hhgoa-{collection}-{path.stem}-part-{index:03d}"
            documents.append(paper(doc_id, f"{path.stem} (part {index})", chunk, collection))

    closed_path = ROOT / "data" / "closed_cases_history.csv"
    with closed_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome",
            "pattern", "first_fraud_txn_id", "txn_ids", "n_txns", "exposure_usd",
            "connected_card_ids", "actions_taken", "report_filed", "analyst_notes",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"closed case CSV missing columns: {sorted(missing)}")
        for row in reader:
            case_id = row["case_id"].strip()
            fields = (
                ("outcome", row["outcome"]),
                ("pattern", row["pattern"]),
                ("customer_id", row["customer_id"]),
                ("card_id", row["card_id"]),
                ("opened_at", row["opened_at"]),
                ("closed_at", row["closed_at"]),
                ("first_fraud_txn_id", row["first_fraud_txn_id"]),
                ("n_txns", row["n_txns"]),
                ("exposure_usd", row["exposure_usd"]),
                ("connected_card_ids", row["connected_card_ids"]),
                ("actions_taken", row["actions_taken"]),
                ("report_filed", row["report_filed"]),
                ("analyst_notes", row["analyst_notes"]),
            )
            body = "\n".join(f"{name}: {value}" for name, value in fields if value)
            if len(body) > MAX_CASE_CHARS:
                raise ValueError(f"closed case {case_id} exceeds single-document limit: {len(body)} chars")
            documents.append(paper(f"hhgoa-closed-{case_id}", f"Closed investigation {case_id}", body, "closed_case"))
            counts["closed_case_source_documents"] += 1
            counts["closed_case_chunks"] += 1

    # The repo contains reference URLs in data/README.md, but no downloaded
    # regulatory documents to ingest as Collection C.
    counts["regulatory_source_documents"] = 0
    counts["regulatory_chunks"] = 0
    counts["total_grip_documents_and_chunks"] = len(documents)
    counts["max_abstract_chars"] = max((len(d["abstract"]) for d in documents), default=0)
    counts["transaction_documents"] = 0
    concept_sets = [set(extract_concepts(d["title"], d["abstract"], max_concepts=5)) for d in documents]
    counts["dry_run_concept_triples"] = sum(len(terms) for terms in concept_sets)
    counts["dry_run_unique_concepts"] = len(set().union(*concept_sets)) if concept_sets else 0
    counts["dry_run_graph_writes"] = 0
    return documents, dict(counts)


if __name__ == "__main__":
    docs, report = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for doc in docs:
            handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
    report["output_file"] = str(OUT.relative_to(ROOT))
    print(json.dumps(report, indent=2, ensure_ascii=False))
