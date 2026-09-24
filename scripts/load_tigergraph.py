"""Create persistent MCP loading jobs and load staged files sequentially."""
from __future__ import annotations

import json
import logging
import sys
import time
import csv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import DATA_DIR, TG_GRAPH_NAME, get_mcp_client

log = logging.getLogger("hhgoa.loader")
STAGING = DATA_DIR / "tigergraph_staging"
CHUNKS = STAGING / "chunks"
EXPECTED_TRANSACTIONS = 590_742
POLL_SECONDS = 5
POLL_LIMIT_SECONDS = 900
REQUEST_TIMEOUT_MS = 120_000
UPLOAD = STAGING / "upload"


def _prepare_upload_files() -> dict[Path, Path]:
    """Create and validate headerless copies for pyTigerGraph file transport."""
    UPLOAD.mkdir(parents=True, exist_ok=True)
    sources = sorted(CHUNKS.glob("transactions_*.csv")) + [
        STAGING / name for name in (
            "devices.csv", "emails.csv", "regions.csv", "closed_cases.csv",
            "closed_case_txns.csv", "closed_case_primary_cards.csv", "closed_case_connected_cards.csv",
        )
    ]
    result: dict[Path, Path] = {}
    for source in sources:
        target = UPLOAD / source.name
        with source.open("r", newline="", encoding="utf-8-sig") as src, target.open(
            "w", newline="", encoding="utf-8"
        ) as dst:
            reader = csv.reader(src)
            first = next(reader, None)
            if first is None:
                raise ValueError(f"Staged file is empty: {source}")
            # All staged side files and transaction files have one header row.
            rows = list(reader)
            writer = csv.writer(dst, lineterminator="\n")
            writer.writerows(rows)
        if source.name.startswith("transactions_"):
            expected_header = [
                "txn_id", "customer_id", "card_id", "ts", "amount", "product_code", "channel", "risk_score",
                "addr1", "addr2", "email", "id_15", "id_23", "device_profile", "device_info", "os", "browser",
                "screen", "device_type", "is_new_for_account", "network", "card_type",
            ]
            if first != expected_header or any(len(row) != len(expected_header) for row in rows):
                raise ValueError(f"Header/column validation failed for {source}")
        if len(rows) == 0:
            raise ValueError(f"Staged file has no data rows: {source}")
        result[source] = target
        log.info("Prepared headerless upload copy %s: %s rows", target.name, f"{len(rows):,}")
    txns = [path for path in result if path.name.startswith("transactions_")]
    total = sum(sum(1 for _ in result[path].open("r", encoding="utf-8")) for path in txns)
    if total != EXPECTED_TRANSACTIONS:
        raise ValueError(f"Headerless transaction copies contain {total:,} rows; expected {EXPECTED_TRANSACTIONS:,}")
    log.info("Verified all 12 transaction upload copies are headerless; total=%s", f"{total:,}")
    return result


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _job_id(result: Any) -> str:
    for row in _walk(result):
        for key in ("job_id", "jobId", "loading_job_id", "loadingJobId"):
            value = row.get(key)
            if value:
                return str(value)
    return ""


def _status(result: Any) -> str:
    for row in _walk(result):
        for key in ("status", "state", "job_status", "jobStatus"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
    return ""


def _create_job(job_name: str, alias: str, node_mappings: list[dict], edge_mappings: list[dict]) -> None:
    client = get_mcp_client()
    result = client.call_tool("tigergraph__create_loading_job", {
        "graph_name": TG_GRAPH_NAME,
        "job_name": job_name,
        "run_job": False,
        "drop_after_run": False,
        "files": [{
            "file_alias": alias,
            "separator": ",",
            "header": "false",
            "quote": "double",
            "node_mappings": node_mappings,
            "edge_mappings": edge_mappings,
        }],
    })
    log.info("Created persistent loading job %s: %s", job_name, json.dumps(result, default=str))


def _run_file(job_name: str, alias: str, path: Path) -> Any:
    client = get_mcp_client()
    result = client.call_tool("tigergraph__run_loading_job_with_file", {
        "graph_name": TG_GRAPH_NAME,
        "file_path": str(path.resolve()),
        "file_tag": alias,
        "job_name": job_name,
        "separator": ",",
        "timeout": REQUEST_TIMEOUT_MS,
        "size_limit": 128_000_000,
    }, timeout_seconds=REQUEST_TIMEOUT_MS // 1000 + 30)
    job_id = _job_id(result)
    if not job_id:
        log.info("MCP returned no job ID for %s; upload tool response: %s", path.name, json.dumps(result, default=str))
        return result

    deadline = time.monotonic() + POLL_LIMIT_SECONDS
    while time.monotonic() < deadline:
        status_result = client.call_tool("tigergraph__get_loading_job_status", {
            "graph_name": TG_GRAPH_NAME,
            "job_id": job_id,
        })
        status = _status(status_result)
        log.info("Load %s job_id=%s status=%s", path.name, job_id, status or "unknown")
        if status in {"FINISHED", "COMPLETED", "SUCCESS", "SUCCEEDED"}:
            return result
        if any(word in status for word in ("FAIL", "ERROR", "CANCEL", "ABORT")):
            raise RuntimeError(
                f"Loading job {job_id} for {path.name} ended with status {status}: {status_result!r}"
            )
        if not status:
            raise RuntimeError(
                f"MCP status response for job {job_id} had no recognized status: {status_result!r}"
            )
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"Loading job {job_id} for {path.name} did not finish within {POLL_LIMIT_SECONDS}s")


def _count(vertex_type: str) -> int:
    response = get_mcp_client().call_tool("tigergraph__get_vertex_count", {
        "graph_name": TG_GRAPH_NAME,
        "vertex_type": vertex_type,
    })
    count = response.get("count") if isinstance(response, dict) else None
    if count is None:
        raise RuntimeError(f"Could not read live {vertex_type} count: {response!r}")
    return int(count)


def _wait_for_count(vertex_type: str, expected: int, previous: int) -> int:
    """Wait for server-side count visibility when the upload tool returns no job ID."""
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        actual = _count(vertex_type)
        if actual == expected:
            return actual
        if actual > expected:
            raise RuntimeError(
                f"Live {vertex_type} count overshot expected {expected:,}: {actual:,} "
                f"(previous {previous:,})"
            )
        time.sleep(POLL_SECONDS)
    actual = _count(vertex_type)
    raise TimeoutError(
        f"Live {vertex_type} count did not reach {expected:,} within 180s; "
        f"currently {actual:,} (previous {previous:,})"
    )


def _edge_count(edge_type: str) -> int:
    response = get_mcp_client().call_tool("tigergraph__get_edge_count", {
        "graph_name": TG_GRAPH_NAME, "edge_type": edge_type,
    })
    count = response.get("count") if isinstance(response, dict) else None
    if count is None:
        raise RuntimeError(f"Could not read live {edge_type} edge count: {response!r}")
    return int(count)


def _wait_for_edge_count(edge_type: str, expected: int, previous: int) -> int:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        actual = _edge_count(edge_type)
        if actual == expected:
            return actual
        if actual > expected:
            raise RuntimeError(f"Live {edge_type} edge count overshot {expected:,}: {actual:,} (previous {previous:,})")
        time.sleep(POLL_SECONDS)
    actual = _edge_count(edge_type)
    raise TimeoutError(f"Live {edge_type} edge count did not reach {expected:,}; currently {actual:,} (previous {previous:,})")


def _distinct_row_keys(path: Path, columns: tuple[int, ...]) -> int:
    keys = set()
    with path.open("r", newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream):
            keys.add(tuple(row[index] for index in columns))
    return len(keys)


def _load_transaction_chunks(max_chunks: int | None = None) -> None:
    chunks = sorted(CHUNKS.glob("transactions_*.csv"))
    if len(chunks) != 12:
        raise ValueError(f"Expected 12 transaction chunks, found {len(chunks)}")
    current = _count("Transaction")
    jobs = get_mcp_client().call_tool("tigergraph__get_loading_jobs", {"graph_name": TG_GRAPH_NAME})
    if "load_hhgoa_transactions" not in (jobs.get("jobs") or []):
        _create_job(
            "load_hhgoa_transactions", "f_transactions",
            [
                {"vertex_type": "Customer", "attribute_mappings": {"customer_id": 1}},
                {"vertex_type": "Card", "attribute_mappings": {
                    "card_id": 2, "customer_id": 1, "network": 20, "card_type": 21,
                }},
                {"vertex_type": "Transaction", "attribute_mappings": {
                    "txn_id": 0, "customer_id": 1, "card_id": 2, "ts": 3, "amount": 4, "product_code": 5,
                    "channel": 6, "risk_score": 7, "addr1": 8, "addr2": 9, "email": 10,
                    "id_15": 11, "id_23": 12, "device_profile": 13,
                }},
            ],
            [
                {"edge_type": "OWNS", "source_column": 1, "target_column": 2},
                {"edge_type": "MADE", "source_column": 2, "target_column": 0},
            ],
        )
    else:
        log.info("Reusing existing persistent transaction loading job")

    if current == EXPECTED_TRANSACTIONS:
        log.info("All transaction chunks are already present; live count is exactly %s", f"{current:,}")
        return

    selected_chunks = chunks if max_chunks is None else chunks[:max_chunks]
    for index, path in enumerate(selected_chunks, 1):
        with path.open(newline="", encoding="utf-8") as stream:
            header = next(stream, "").rstrip("\r\n")
            rows = sum(1 for _ in stream)
        if header != ",".join([
            "txn_id", "customer_id", "card_id", "ts", "amount", "product_code", "channel", "risk_score",
            "addr1", "addr2", "email", "id_15", "id_23", "device_profile", "device_info", "os", "browser",
            "screen", "device_type", "is_new_for_account", "network", "card_type",
        ]):
            raise ValueError(f"Header mismatch in {path}")
        expected_before = sum(
            min(50_000, EXPECTED_TRANSACTIONS - (chunk_index - 1) * 50_000)
            for chunk_index in range(1, index)
        )
        expected_after = expected_before + rows
        if current == expected_after:
            log.info("Chunk %d/12 already verified in live graph; skipping duplicate upload", index)
            continue
        if current != expected_before:
            raise RuntimeError(
                f"Before chunk {index}, live Transaction count is {current:,}; "
                f"expected {expected_before:,}. Stopping to avoid a duplicate or gap."
            )
        _run_file("load_hhgoa_transactions", "f_transactions", UPLOAD / path.name)
        new_count = _wait_for_count("Transaction", expected_after, current)
        increase = new_count - current
        if increase != rows:
            raise RuntimeError(
                f"After {path.name}, Transaction count increased by {increase:,}; "
                f"expected {rows:,} (total {new_count:,}, prior {current:,})"
            )
        log.info("Verified chunk %d/12: +%s Transaction rows (total %s)", index, f"{increase:,}", f"{new_count:,}")
        current = new_count

    if max_chunks is None and current != EXPECTED_TRANSACTIONS:
        raise RuntimeError(f"Final Transaction count is {current:,}; expected {EXPECTED_TRANSACTIONS:,}")


def _load_single_file(
    job_name: str,
    alias: str,
    path: Path,
    nodes: list[dict],
    edges: list[dict],
    vertex_keys: dict[str, tuple[int, ...]] | None = None,
    edge_types: list[str] | None = None,
) -> None:
    upload = UPLOAD / path.name
    expected_vertices = {
        name: _distinct_row_keys(upload, key_columns)
        for name, key_columns in (vertex_keys or {}).items()
    }
    expected_edges = {
        name: _distinct_row_keys(upload, (0, 1))
        for name in (edge_types or [])
    }
    prior_vertices = {name: _count(name) for name in (vertex_keys or {})}
    prior_edges = {name: _edge_count(name) for name in (edge_types or [])}
    if all(prior_vertices[name] == expected_vertices[name] for name in expected_vertices) and all(
        prior_edges[name] == expected_edges[name] for name in expected_edges
    ):
        log.info("%s already matches its exact live counts; skipping duplicate upload", path.name)
        return
    jobs = get_mcp_client().call_tool("tigergraph__get_loading_jobs", {"graph_name": TG_GRAPH_NAME})
    if job_name not in (jobs.get("jobs") or []):
        _create_job(job_name, alias, nodes, edges)
    else:
        log.info("Reusing existing persistent loading job %s", job_name)
    _run_file(job_name, alias, upload)
    for vertex_type, key_columns in (vertex_keys or {}).items():
        expected = expected_vertices[vertex_type]
        actual = _wait_for_count(vertex_type, expected, prior_vertices[vertex_type])
        log.info("Verified %s count after %s: +%s (total %s)", vertex_type, path.name,
                 f"{actual-prior_vertices[vertex_type]:,}", f"{actual:,}")
    for edge_type in (edge_types or []):
        expected = expected_edges[edge_type]
        actual = _wait_for_edge_count(edge_type, expected, prior_edges[edge_type])
        log.info("Verified %s edge count after %s: +%s (total %s)", edge_type, path.name,
                 f"{actual-prior_edges[edge_type]:,}", f"{actual:,}")


def load_all() -> None:
    upload_map = _prepare_upload_files()
    _load_transaction_chunks()
    _load_single_file(
        "load_hhgoa_devices", "f_devices", STAGING / "devices.csv",
        [{"vertex_type": "DeviceProfile", "attribute_mappings": {
            "device_profile_id": 1, "device_info": 2, "os": 3, "browser": 4,
            "screen": 5, "device_type": 6, "is_new_for_account": 7,
        }}],
        [{"edge_type": "FROM_DEVICE", "source_column": 0, "target_column": 1}],
        {"DeviceProfile": (1,)}, ["FROM_DEVICE"],
    )
    _load_single_file(
        "load_hhgoa_emails", "f_emails", STAGING / "emails.csv",
        [{"vertex_type": "EmailDomain", "attribute_mappings": {"domain": 1}}],
        [{"edge_type": "PURCHASER_EMAIL", "source_column": 0, "target_column": 1}],
        {"EmailDomain": (1,)}, ["PURCHASER_EMAIL"],
    )
    _load_single_file(
        "load_hhgoa_regions", "f_regions", STAGING / "regions.csv",
        [{"vertex_type": "BillingRegion", "attribute_mappings": {"addr1": 1, "addr2": 2}}],
        [{"edge_type": "BILLED_IN", "source_column": 0, "target_column": 1}],
        {"BillingRegion": (1,)}, ["BILLED_IN"],
    )
    _load_single_file(
        "load_hhgoa_closed_cases", "f_closed_cases", STAGING / "closed_cases.csv",
        [{"vertex_type": "ClosedCase", "attribute_mappings": {
            "case_id": 0, "customer_id": 1, "card_id": 2, "opened_at": 3, "closed_at": 4,
            "outcome": 5, "pattern": 6, "exposure_usd": 7, "n_txns": 8, "actions_taken": 9,
            "report_filed": 10, "analyst_notes": 11, "connected_card_ids": 12,
        }}],
        [], {"ClosedCase": (0,)}, [],
    )
    _load_single_file(
        "load_hhgoa_closed_case_txns", "f_closed_case_txns", STAGING / "closed_case_txns.csv", [],
        [{"edge_type": "INVOLVES", "source_column": 0, "target_column": 1}], {}, ["INVOLVES"],
    )
    _load_single_file(
        "load_hhgoa_closed_case_primary_cards", "f_closed_case_primary_cards", STAGING / "closed_case_primary_cards.csv", [],
        [{"edge_type": "ON_CARD", "source_column": 0, "target_column": 1}], {}, ["ON_CARD"],
    )
    _load_single_file(
        "load_hhgoa_closed_case_connected_cards", "f_closed_case_connected_cards", STAGING / "closed_case_connected_cards.csv", [],
        [{"edge_type": "CONNECTED_TO", "source_column": 0, "target_column": 1}], {}, ["CONNECTED_TO"],
    )

    if _count("Transaction") != EXPECTED_TRANSACTIONS:
        raise RuntimeError("Transaction count changed after loading related files")
    log.info("All source data loaded; final Transaction count is exactly %s", f"{EXPECTED_TRANSACTIONS:,}")

    # Keep definitions through all successful loads; drop only after the final
    # count check, never during the sequential chunk loop.
    for name in [
        "load_hhgoa_transactions", "load_hhgoa_devices", "load_hhgoa_emails", "load_hhgoa_regions",
        "load_hhgoa_closed_cases", "load_hhgoa_closed_case_txns", "load_hhgoa_closed_case_primary_cards",
        "load_hhgoa_closed_case_connected_cards",
    ]:
        result = get_mcp_client().call_tool("tigergraph__drop_loading_job", {
            "graph_name": TG_GRAPH_NAME, "job_name": name,
        })
        log.info("Dropped completed loading job %s: %s", name, json.dumps(result, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "--first-transaction-chunk" in sys.argv:
        _prepare_upload_files()
        _load_transaction_chunks(max_chunks=1)
    elif "--transactions-only" in sys.argv:
        _prepare_upload_files()
        _load_transaction_chunks()
    else:
        load_all()
