"""Stream the source CSVs into canonical TigerGraph loading files.

The output preserves CsvGraphStore's deterministic card-id assignment while
keeping the 708 MB transaction file out of memory.
"""
from __future__ import annotations

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import DATA_DIR
from src.csv_store import _device_profile, _parse_ts, _sid, _split_ids

OUT = DATA_DIR / "tigergraph_staging"
CHUNKS = OUT / "chunks"
CHUNK_ROWS = 50_000
EXPECTED_TRANSACTIONS = 590_742
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

TXN_FIELDS = [
    "txn_id", "customer_id", "card_id", "ts", "amount", "product_code", "channel",
    "risk_score", "addr1", "addr2", "email", "id_15", "id_23", "device_profile",
    "device_info", "os", "browser", "screen", "device_type", "is_new_for_account", "network", "card_type",
]
CLOSED_FIELDS = [
    "case_id", "customer_id", "card_id", "opened_at", "closed_at", "outcome", "pattern",
    "exposure_usd", "n_txns", "actions_taken", "report_filed", "analyst_notes", "connected_card_ids",
]


def _clean(value) -> str:
    return str(value or "").replace("\x00", "").replace("\r", " ").replace("\n", " ").replace('"', "'").strip()


def _read_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)


def _split_transactions(txn_path: Path) -> list[Path]:
    """Split the trimmed CSV into upload-sized files with a repeated header."""
    CHUNKS.mkdir(parents=True, exist_ok=True)
    for old_chunk in CHUNKS.glob("transactions_*.csv"):
        old_chunk.unlink()

    chunk_paths: list[Path] = []
    total_rows = 0
    chunk_rows = 0
    writer = None
    output = None
    with txn_path.open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        header = next(reader)
        for row in reader:
            if writer is None or chunk_rows == CHUNK_ROWS:
                if output is not None:
                    output.close()
                chunk_path = CHUNKS / f"transactions_{len(chunk_paths) + 1:03d}.csv"
                output = chunk_path.open("w", newline="", encoding="utf-8")
                writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
                writer.writerow(header)
                chunk_paths.append(chunk_path)
                chunk_rows = 0
            writer.writerow(row)
            chunk_rows += 1
            total_rows += 1
    if output is not None:
        output.close()

    if total_rows != EXPECTED_TRANSACTIONS:
        raise ValueError(
            f"Expected {EXPECTED_TRANSACTIONS:,} transactions, found {total_rows:,}"
        )

    verified_rows = 0
    for chunk_path in chunk_paths:
        with chunk_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream)
            chunk_header = next(reader, None)
            if chunk_header != header:
                raise ValueError(f"Invalid or missing header in {chunk_path}")
            verified_rows += sum(1 for _ in reader)
    if verified_rows != EXPECTED_TRANSACTIONS:
        raise ValueError(
            f"Chunk verification found {verified_rows:,} rows, expected {EXPECTED_TRANSACTIONS:,}"
        )
    log.info(
        "Verified %s chunks, each with a repeated %s-column header and %s transaction rows",
        len(chunk_paths), len(header), f"{verified_rows:,}",
    )
    return chunk_paths


def _write_side_files(txn_path: Path) -> None:
    """Create compact, non-empty mappings for optional graph entities/edges."""
    side_specs = {
        "devices.csv": ["txn_id", "device_profile", "device_info", "os", "browser", "screen", "device_type", "is_new_for_account"],
        "emails.csv": ["txn_id", "email"],
        "regions.csv": ["txn_id", "addr1", "addr2"],
    }
    writers: dict[str, csv.DictWriter] = {}
    streams = {}
    try:
        for filename, fields in side_specs.items():
            stream = (OUT / filename).open("w", newline="", encoding="utf-8")
            streams[filename] = stream
            writer = csv.DictWriter(stream, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writers[filename] = writer

        for row in _read_rows(txn_path):
            if row.get("device_profile"):
                writers["devices.csv"].writerow({key: row.get(key, "") for key in side_specs["devices.csv"]})
            if row.get("email"):
                writers["emails.csv"].writerow({key: row.get(key, "") for key in side_specs["emails.csv"]})
            if row.get("addr1"):
                writers["regions.csv"].writerow({key: row.get(key, "") for key in side_specs["regions.csv"]})
    finally:
        for stream in streams.values():
            stream.close()


def _assign_card_ids() -> dict[tuple[str, str], str]:
    pack = list(_read_rows(DATA_DIR / "case_pack.csv"))
    closed = list(_read_rows(DATA_DIR / "closed_cases_history.csv"))
    known_txn_to_card: dict[str, str] = {}
    for row in pack:
        known_txn_to_card[_sid(row.get("flagged_txn_id"))] = _sid(row.get("card_id"))
    for row in closed:
        cid = _sid(row.get("card_id"))
        for tid in _split_ids(row.get("txn_ids")):
            known_txn_to_card[_sid(tid)] = cid
        first = _sid(row.get("first_fraud_txn_id"))
        if first:
            known_txn_to_card[first] = cid

    known_tid_to_pair: dict[str, tuple[str, str]] = {}
    first_seen: dict[tuple[str, str], datetime] = {}
    known_ids = set(known_txn_to_card)
    for row in _read_rows(DATA_DIR / "transactions.csv"):
        tid = _sid(row.get("TransactionID"))
        customer, card1 = _sid(row.get("customer_id")), _sid(row.get("card1"))
        pair = (customer, card1)
        if tid in known_ids:
            known_tid_to_pair[tid] = pair
        ts = _parse_ts(row.get("ts")) or datetime.min
        if pair not in first_seen or ts < first_seen[pair]:
            first_seen[pair] = ts

    pair_to_card: dict[tuple[str, str], str] = {}
    used: dict[str, set[str]] = {}
    # Match CsvGraphStore's map insertion order when a known pair is assigned.
    for txn_id, card_id in known_txn_to_card.items():
        pair = known_tid_to_pair.get(txn_id)
        if pair:
            pair_to_card[pair] = card_id
            used.setdefault(pair[0], set()).add(card_id)
    for customer, card1 in sorted(first_seen, key=lambda p: (first_seen[p], p[0], p[1])):
        pair = (customer, card1)
        if pair in pair_to_card:
            continue
        assigned = used.setdefault(customer, set())
        number = 1
        while f"{customer}-K{number}" in assigned:
            number += 1
        card_id = f"{customer}-K{number}"
        pair_to_card[pair] = card_id
        assigned.add(card_id)
    return pair_to_card


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pair_to_card = _assign_card_ids()
    identities = {}
    for row in _read_rows(DATA_DIR / "identity.csv"):
        tid = _sid(row.get("TransactionID"))
        identities[tid] = row
    txn_path = OUT / "transactions.csv"
    with txn_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TXN_FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for raw in _read_rows(DATA_DIR / "transactions.csv"):
            txn_id = _sid(raw.get("TransactionID"))
            ident = identities.get(txn_id, {})
            merged = {**raw, **ident}
            email = _sid(merged.get("R_emaildomain") or merged.get("P_emaildomain"))
            profile = _device_profile(merged)
            values = {
                "txn_id": txn_id,
                "customer_id": _sid(raw.get("customer_id")),
                "card_id": pair_to_card.get((_sid(raw.get("customer_id")), _sid(raw.get("card1"))), ""),
                "ts": _sid(raw.get("ts")),
                "amount": _sid(raw.get("TransactionAmt")) or "0",
                "product_code": _sid(raw.get("ProductCD")),
                "channel": _sid(raw.get("channel")),
                "risk_score": _sid(raw.get("risk_score")) or "0",
                "addr1": _sid(raw.get("addr1")),
                "addr2": _sid(raw.get("addr2")),
                "email": email,
                "id_15": _sid(ident.get("id_15")),
                "id_23": _sid(ident.get("id_23")),
                "device_profile": profile,
                "device_info": _sid(ident.get("DeviceInfo")),
                "os": _sid(ident.get("id_30")),
                "browser": _sid(ident.get("id_31")),
                "screen": _sid(ident.get("id_33")),
                "device_type": _sid(ident.get("DeviceType")),
                "is_new_for_account": str(_sid(ident.get("id_15")).lower() == "new").lower(),
                "network": _sid(raw.get("card4")),
                "card_type": _sid(raw.get("card6")),
            }
            writer.writerow({key: _clean(value) for key, value in values.items()})
    log.info("Prepared %s trimmed transaction rows", f"{sum(1 for _ in _read_rows(txn_path)):,}")
    _split_transactions(txn_path)
    _write_side_files(txn_path)

    case_path = OUT / "closed_cases.csv"
    txn_edges_path = OUT / "closed_case_txns.csv"
    primary_cards_path = OUT / "closed_case_primary_cards.csv"
    connected_cards_path = OUT / "closed_case_connected_cards.csv"
    with case_path.open("w", newline="", encoding="utf-8") as cases_stream, \
         txn_edges_path.open("w", newline="", encoding="utf-8") as txn_stream, \
         primary_cards_path.open("w", newline="", encoding="utf-8") as primary_stream, \
         connected_cards_path.open("w", newline="", encoding="utf-8") as connected_stream:
        case_writer = csv.DictWriter(cases_stream, fieldnames=CLOSED_FIELDS, quoting=csv.QUOTE_MINIMAL)
        txn_writer = csv.writer(txn_stream, quoting=csv.QUOTE_MINIMAL)
        primary_writer = csv.writer(primary_stream, quoting=csv.QUOTE_MINIMAL)
        connected_writer = csv.writer(connected_stream, quoting=csv.QUOTE_MINIMAL)
        case_writer.writeheader()
        txn_writer.writerow(["case_id", "txn_id"])
        primary_writer.writerow(["case_id", "card_id"])
        connected_writer.writerow(["case_id", "card_id"])
        for row in _read_rows(DATA_DIR / "closed_cases_history.csv"):
            case_id = _sid(row.get("case_id"))
            card_id = _sid(row.get("card_id"))
            connected = _split_ids(row.get("connected_card_ids"))
            case_writer.writerow({
                "case_id": case_id,
                "customer_id": _sid(row.get("customer_id")),
                "card_id": card_id,
                "opened_at": _sid(row.get("opened_at")),
                "closed_at": _sid(row.get("closed_at")),
                "outcome": _sid(row.get("outcome")),
                "pattern": _sid(row.get("pattern")),
                "exposure_usd": _sid(row.get("exposure_usd")) or "0",
                "n_txns": _sid(row.get("n_txns")) or "0",
                "actions_taken": _clean(row.get("actions_taken")),
                "report_filed": _sid(row.get("report_filed")).lower() in {"true", "1", "yes"},
                "analyst_notes": _clean(row.get("analyst_notes"))[:500],
                "connected_card_ids": "|".join(connected),
            })
            txn_ids = list(dict.fromkeys(_split_ids(row.get("txn_ids")) + [_sid(row.get("first_fraud_txn_id"))]))
            for txn_id in filter(None, txn_ids):
                txn_writer.writerow([case_id, txn_id])
            if card_id:
                primary_writer.writerow([case_id, card_id])
            for connected_card in connected:
                connected_writer.writerow([case_id, connected_card])
    log.info("Prepared closed-case vertices and links in %s", OUT)


if __name__ == "__main__":
    prepare()
