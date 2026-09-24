"""
In-process graph over data/*.csv. Cached after first load.

card_id is not a column on transactions.csv. We bind K-index IDs using
case_pack + closed_cases_history as ground truth, then fill remaining
(customer_id, card1) pairs with the next unused Kn.

Implemented with the stdlib csv module so the agent runs even when pandas
native DLLs are blocked by Windows Application Control.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import (
    ANSWERS_DIR,
    CARD_WINDOW_HOURS,
    CUSTOMER_HISTORY_DAYS,
    DATA_DIR,
    SHARED_ORIGIN_WINDOW_DAYS,
    SIMILAR_CASES_TOP_K,
)

log = logging.getLogger(__name__)

TXN_COLS = [
    "TransactionID",
    "TransactionAmt",
    "ProductCD",
    "card1",
    "addr1",
    "addr2",
    "P_emaildomain",
    "R_emaildomain",
    "customer_id",
    "ts",
    "channel",
    "risk_score",
    "M4",
    "M5",
    "M6",
]
ID_COLS = [
    "TransactionID",
    "id_15",
    "id_23",
    "id_30",
    "id_31",
    "id_33",
    "DeviceType",
    "DeviceInfo",
]


def _sid(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("", "nan", "none", "null"):
        return ""
    if s.endswith(".0"):
        head = s[:-2]
        if head.replace("-", "", 1).isdigit():
            return head
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except ValueError:
        pass
    return s


def _fnum(v: Any) -> float:
    try:
        if v is None or str(v).strip() == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_ts(v: Any) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


_GENERIC_DEVICES = {"windows", "macos", "mac os", "ios", "linux", "android", "other"}


def _device_profile(row: dict) -> str:
    info = _sid(row.get("DeviceInfo"))
    os_name = _sid(row.get("id_30"))
    browser = _sid(row.get("id_31"))
    screen = _sid(row.get("id_33"))
    # OS-only labels like "Windows" are shared by thousands of cards — not R6 evidence.
    if info.lower() in _GENERIC_DEVICES or not info:
        if not (os_name and browser and screen):
            return ""
    parts = [p for p in (info, os_name, browser, screen, _sid(row.get("DeviceType"))) if p]
    raw = "|".join(parts)
    if not raw:
        return ""
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    label = info or _sid(row.get("DeviceType")) or "device"
    return f"{label[:40]}#{digest}"


def _split_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    return [p.strip() for p in str(raw).replace(",", "|").split("|") if p.strip()]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class CsvGraphStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DATA_DIR)
        self.closed_rows: list[dict] = []
        self.pack_rows: list[dict] = []
        self.by_txn: dict[str, dict] = {}
        self.by_card: dict[str, list[dict]] = {}
        self.by_customer: dict[str, list[dict]] = {}
        self.by_device: dict[str, list[dict]] = {}
        self.by_region: dict[str, list[dict]] = {}
        self.by_email: dict[str, list[dict]] = {}
        self.all_closed_ids: set[str] = set()
        self._load()

    def _load(self) -> None:
        tx_path = self.data_dir / "transactions.csv"
        id_path = self.data_dir / "identity.csv"
        closed_path = self.data_dir / "closed_cases_history.csv"
        pack_path = self.data_dir / "case_pack.csv"
        if not tx_path.exists():
            raise FileNotFoundError(f"Missing {tx_path}")

        log.info("Loading transactions from %s", tx_path)
        ident: dict[str, dict] = {}
        if id_path.exists():
            for raw in _read_csv(id_path):
                tid = _sid(raw.get("TransactionID"))
                ident[tid] = {k: raw.get(k, "") for k in ID_COLS}

        self.pack_rows = _read_csv(pack_path) if pack_path.exists() else []
        self.closed_rows = _read_csv(closed_path) if closed_path.exists() else []
        self.all_closed_ids = {_sid(r.get("case_id")) for r in self.closed_rows}

        slim: list[dict] = []
        with tx_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                tid = _sid(raw.get("TransactionID"))
                row = {k: raw.get(k, "") for k in TXN_COLS}
                extra = ident.get(tid) or {}
                row.update(extra)
                row["TransactionID"] = tid
                row["customer_id"] = _sid(row.get("customer_id"))
                row["card1"] = _sid(row.get("card1"))
                row["addr1"] = _sid(row.get("addr1"))
                row["P_emaildomain"] = _sid(row.get("P_emaildomain"))
                row["R_emaildomain"] = _sid(row.get("R_emaildomain"))
                row["channel"] = _sid(row.get("channel"))
                row["ProductCD"] = _sid(row.get("ProductCD"))
                row["ts"] = _parse_ts(row.get("ts"))
                row["TransactionAmt"] = _fnum(row.get("TransactionAmt"))
                row["risk_score"] = _fnum(row.get("risk_score")) if _sid(row.get("risk_score")) else 0.0
                row["id_15"] = _sid(row.get("id_15"))
                row["id_23"] = _sid(row.get("id_23"))
                row["DeviceInfo"] = _sid(row.get("DeviceInfo"))
                row["DeviceType"] = _sid(row.get("DeviceType"))
                slim.append(row)

        pair_to_card = self._assign_card_ids(slim)
        for row in slim:
            row["card_id"] = pair_to_card.get(
                (row["customer_id"], row["card1"]),
                f"{row['customer_id']}-K1",
            )
            row["device_profile"] = _device_profile(row)
            tid = row["TransactionID"]
            self.by_txn[tid] = row
            self.by_card.setdefault(row["card_id"], []).append(row)
            self.by_customer.setdefault(row["customer_id"], []).append(row)
            if row.get("device_profile"):
                self.by_device.setdefault(row["device_profile"], []).append(row)
            if row.get("addr1"):
                self.by_region.setdefault(row["addr1"], []).append(row)
            email = row.get("R_emaildomain") or row.get("P_emaildomain")
            if email:
                self.by_email.setdefault(email, []).append(row)

        def _ts_key(r: dict):
            return r["ts"] or datetime.min

        for mapping in (self.by_card, self.by_customer):
            for key, rows in mapping.items():
                mapping[key] = sorted(rows, key=_ts_key)

        log.info("CSV graph ready: %s txns, %s cards", len(self.by_txn), len(self.by_card))

    def _assign_card_ids(self, rows: list[dict]) -> dict[tuple[str, str], str]:
        known_txn_to_card: dict[str, str] = {}
        for row in self.pack_rows:
            known_txn_to_card[_sid(row.get("flagged_txn_id"))] = _sid(row.get("card_id"))
        for row in self.closed_rows:
            cid = _sid(row.get("card_id"))
            for tid in _split_ids(row.get("txn_ids")):
                known_txn_to_card[_sid(tid)] = cid
            first = _sid(row.get("first_fraud_txn_id"))
            if first:
                known_txn_to_card[first] = cid

        by_tid = {r["TransactionID"]: r for r in rows}
        pair_to_card: dict[tuple[str, str], str] = {}
        used: dict[str, set[str]] = {}
        for tid, card_id in known_txn_to_card.items():
            rec = by_tid.get(tid)
            if not rec:
                continue
            key = (rec["customer_id"], rec["card1"])
            pair_to_card[key] = card_id
            used.setdefault(rec["customer_id"], set()).add(card_id)

        remaining = sorted(
            {(r["customer_id"], r["card1"], r["ts"] or datetime.min) for r in rows},
            key=lambda t: t[2],
        )
        seen_pairs: set[tuple[str, str]] = set()
        for cust, c1, _ts in remaining:
            key = (cust, c1)
            if key in seen_pairs or key in pair_to_card:
                seen_pairs.add(key)
                continue
            taken = used.setdefault(cust, set())
            n = 1
            while f"{cust}-K{n}" in taken:
                n += 1
            cid = f"{cust}-K{n}"
            pair_to_card[key] = cid
            taken.add(cid)
            seen_pairs.add(key)
        return pair_to_card

    def card_window(self, card_id: str, flagged_txn_id: str, hours: int | None = None) -> dict:
        hours = hours or CARD_WINDOW_HOURS
        flagged = self.by_txn.get(_sid(flagged_txn_id))
        rows = list(self.by_card.get(card_id, []))
        if flagged is None:
            return {
                "affected_txn_ids": [],
                "activity_dates": [],
                "txns": [],
                "claim_text": f"Flagged transaction {flagged_txn_id} was not found.",
            }
        center = flagged["ts"]
        if center is None:
            window = rows
        else:
            delta = timedelta(hours=hours)
            window = [r for r in rows if r["ts"] is not None and abs(r["ts"] - center) <= delta]
        if flagged["TransactionID"] not in {r["TransactionID"] for r in window}:
            window.append(flagged)
        window = sorted(window, key=lambda r: r["ts"] or datetime.min)
        ids = [r["TransactionID"] for r in window]
        dates = [_date(r["ts"]) for r in window if r["ts"] is not None]
        activity = [dates[0], dates[-1]] if dates else []
        amounts = [float(r["TransactionAmt"]) for r in window]
        claim = (
            f"Card {card_id} has {len(window)} transaction(s) within ±{hours}h of "
            f"{flagged_txn_id} totaling ${sum(amounts):.2f}."
        )
        return {
            "affected_txn_ids": ids,
            "activity_dates": activity,
            "txns": [_public_txn(r) for r in window],
            "exposure_usd": round(sum(amounts), 2),
            "claim_text": claim,
        }

    def device_neighbors(self, txn_id: str, window_days: int | None = None) -> dict:
        window_days = window_days or SHARED_ORIGIN_WINDOW_DAYS
        flagged = self.by_txn.get(_sid(txn_id))
        if not flagged or not flagged.get("device_profile"):
            return {"card_ids": [], "device_profiles": [], "txns": []}
        profile = flagged["device_profile"]
        center = flagged["ts"]
        others: dict[str, dict] = {}
        for row in self.by_device.get(profile, []):
            if row["card_id"] == flagged["card_id"]:
                continue
            if center and row["ts"] and abs(row["ts"] - center) > timedelta(days=window_days):
                continue
            others[row["card_id"]] = row
        # Huge fan-out means the profile is still too generic to cite.
        if len(others) > 25:
            return {"card_ids": [], "device_profiles": [], "txns": []}
        return {
            "card_ids": sorted(others),
            "device_profiles": [profile] if others else [],
            "txns": [_public_txn(r) for r in others.values()],
        }

    def region_cluster(self, txn_id: str, window_days: int = 7) -> dict:
        flagged = self.by_txn.get(_sid(txn_id))
        if not flagged or not flagged.get("addr1"):
            return {"card_ids": [], "txns": []}
        region = flagged["addr1"]
        center = flagged["ts"]
        others: dict[str, dict] = {}
        for row in self.by_region.get(region, []):
            if row["card_id"] == flagged["card_id"]:
                continue
            if center and row["ts"] and abs(row["ts"] - center) > timedelta(days=window_days):
                continue
            others[row["card_id"]] = row
        cards = sorted(others)
        if len(cards) > 25:
            cards = cards[:25]
        return {"card_ids": cards, "region": region, "txns": [_public_txn(others[c]) for c in cards[:10]]}

    def email_cluster(self, txn_id: str, window_days: int = 7) -> dict:
        flagged = self.by_txn.get(_sid(txn_id))
        if not flagged:
            return {"card_ids": [], "txns": []}
        email = flagged.get("R_emaildomain") or flagged.get("P_emaildomain")
        if not email:
            return {"card_ids": [], "txns": []}
        center = flagged["ts"]
        others: dict[str, dict] = {}
        for row in self.by_email.get(email, []):
            if row["card_id"] == flagged["card_id"]:
                continue
            if center and row["ts"] and abs(row["ts"] - center) > timedelta(days=window_days):
                continue
            others[row["card_id"]] = row
        cards = sorted(others)
        if len(cards) > 25:
            cards = cards[:25]
        return {"card_ids": cards, "email": email, "txns": [_public_txn(others[c]) for c in cards[:10]]}

    def customer_history(self, customer_id: str, days: int | None = None) -> dict:
        days = days or CUSTOMER_HISTORY_DAYS
        rows = self.by_customer.get(customer_id, [])
        if not rows:
            return {"txns": [], "regions": [], "products": [], "channels": [], "mean_amt": 0.0, "n": 0}
        stamped = [r for r in rows if r["ts"] is not None]
        latest = max((r["ts"] for r in stamped), default=None)
        if latest is not None:
            cutoff = latest - timedelta(days=days)
            rows = [r for r in stamped if r["ts"] >= cutoff]
        amts = [float(r["TransactionAmt"]) for r in rows]
        regions = sorted({r.get("addr1") for r in rows if r.get("addr1")})
        products = sorted({r.get("ProductCD") for r in rows if r.get("ProductCD")})
        channels = sorted({r.get("channel") for r in rows if r.get("channel")})
        cards = sorted({r["card_id"] for r in rows})
        return {
            "txns": [_public_txn(r) for r in rows[-40:]],
            "regions": regions,
            "products": products,
            "channels": channels,
            "card_ids": cards,
            "mean_amt": round(sum(amts) / len(amts), 2) if amts else 0.0,
            "n": len(rows),
        }

    def closed_case_similarity(self, customer_id: str, card_id: str, top_k: int | None = None) -> dict:
        top_k = top_k or SIMILAR_CASES_TOP_K
        scored: list[tuple[float, dict]] = []
        for row in self.closed_rows:
            score = 0.0
            if _sid(row.get("customer_id")) == customer_id:
                score += 5
            if _sid(row.get("card_id")) == card_id:
                score += 4
            connected = _split_ids(row.get("connected_card_ids"))
            if card_id in connected:
                score += 3
            notes = str(row.get("analyst_notes") or "").lower()
            if customer_id.lower() in notes or card_id.lower() in notes:
                score += 1
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        matches = []
        for score, row in scored[:top_k]:
            cid = _sid(row.get("case_id"))
            matches.append(
                {
                    "case_id": cid,
                    "score": score,
                    "pattern": _sid(row.get("pattern")),
                    "outcome": _sid(row.get("outcome")),
                    "notes": str(row.get("analyst_notes") or "")[:500],
                }
            )
        return {"matches": matches}

    def known_ids_for(self, card_id: str, customer_id: str) -> set[str]:
        ids: set[str] = {card_id, customer_id}
        for row in self.by_customer.get(customer_id, []):
            ids.add(row["TransactionID"])
            ids.add(row["card_id"])
            if row.get("device_profile"):
                ids.add(row["device_profile"])
        for row in self.by_card.get(card_id, []):
            ids.add(row["TransactionID"])
        ids |= self.all_closed_ids
        for row in self.by_customer.get(customer_id, []):
            if row.get("device_profile"):
                for n in self.by_device.get(row["device_profile"], []):
                    ids.add(n["card_id"])
                    ids.add(n["TransactionID"])
            if row.get("addr1"):
                for n in self.by_region.get(row["addr1"], [])[:200]:
                    ids.add(n["card_id"])
                    ids.add(n["TransactionID"])
        memory = ANSWERS_DIR / "_graph_memory.jsonl"
        if memory.exists():
            for line in memory.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    ids.add(_sid(rec.get("case_id")))
                    ids.add(_sid(rec.get("graph_case_id")))
                except json.JSONDecodeError:
                    continue
        return {i for i in ids if i}

    def write_case(self, case, case_id: str) -> str:
        ANSWERS_DIR.mkdir(parents=True, exist_ok=True)
        graph_case_id = f"G-{case_id}"
        payload = {
            "graph_case_id": graph_case_id,
            "case_id": case_id,
            "status": getattr(case.status, "value", case.status),
            "verdict": getattr(case.verdict, "value", case.verdict),
            "pattern": getattr(case.pattern, "value", case.pattern),
            "exposure_usd": case.exposure_usd,
            "summary": case.summary,
        }
        path = ANSWERS_DIR / "_graph_memory.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        return graph_case_id

    def derive_hints(self, evidence: dict, flagged_txn_id: str, card_id: str, customer_id: str) -> dict:
        flagged = self.by_txn.get(_sid(flagged_txn_id), {})
        window = evidence.get("card_window") or {}
        txns = window.get("txns") or []
        hist = evidence.get("customer_history") or {}
        devices = evidence.get("device_neighbors") or {}
        regions = evidence.get("region_cluster") or {}
        emails = evidence.get("email_cluster") or {}

        small_online = [
            t for t in txns
            if t.get("channel") == "online" and float(t.get("amount") or 0) < 5
        ]
        large = [t for t in txns if float(t.get("amount") or 0) > 100]
        testing = len(small_online) >= 3 and bool(large)

        id_15 = _sid(flagged.get("id_15")).lower()
        new_device = id_15 == "new"
        channel = _sid(flagged.get("channel"))
        addr1 = _sid(flagged.get("addr1"))
        hist_regions = set(hist.get("regions") or [])
        out_of_region = channel == "in_person" and addr1 and addr1 not in hist_regions and len(hist_regions) >= 1

        mean_amt = float(hist.get("mean_amt") or 0)
        amt = float(flagged.get("TransactionAmt") or 0)
        unusual_amt = mean_amt > 0 and amt > max(50, mean_amt * 3)
        cnp = channel == "online" and (unusual_amt or new_device)

        mixed = set(hist.get("channels") or []) == {"online", "in_person"} and channel == "online"
        takeover = mixed and (new_device or _sid(flagged.get("id_23")).lower() in {"anonymous", "hidden"})

        n_dev = len(devices.get("card_ids") or [])
        n_reg = len(regions.get("card_ids") or [])
        n_em = len(emails.get("card_ids") or [])
        # Tight clusters only — city-wide / gmail-wide overlap is not R6.
        shared_device = 1 <= n_dev <= 20
        shared_region = 2 <= n_reg <= 12
        shared_email = 2 <= n_em <= 12

        exposure = float(window.get("exposure_usd") or amt)
        evidence_count = 1 + int(shared_device) + int(bool(txns))
        if testing:
            pattern = "card_testing"
            prob = 0.82
        elif takeover:
            pattern = "account_takeover"
            prob = 0.74
        elif new_device and cnp:
            pattern = "card_not_present_new_device"
            prob = 0.68
        elif out_of_region:
            pattern = "out_of_region_use"
            prob = 0.62
        elif cnp:
            pattern = "card_not_present_fraud"
            prob = 0.58
        else:
            pattern = "none"
            prob = 0.28

        if shared_device:
            prob = min(0.95, prob + 0.12)
        single = not (testing or shared_device or (cnp and new_device) or out_of_region)

        closed_same = [
            m for m in (evidence.get("closed_case_similarity") or {}).get("matches") or []
            if m.get("outcome") == "confirmed_fraud"
        ]

        return {
            "fraud_probability": round(prob, 4),
            "pattern": pattern,
            "exposure_usd": round(exposure, 2),
            "shared_device_flag": shared_device,
            "shared_region_flag": shared_region,
            "shared_email_flag": shared_email,
            "single_signal_only": single,
            "evidence_count": max(1, min(evidence_count, 4)),
            "evidence_sufficiency": 0.55 if single else 0.72,
            "undocumented_coordinated": False,
            "dispute_matches_recurring": False,
            "confirmed_cards_count": min(len({m.get("case_id") for m in closed_same}), 3),
            "id_15": _sid(flagged.get("id_15")),
            "channel": channel,
            "amount": amt,
        }


def _date(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d")


def _public_txn(row: dict) -> dict:
    ts = row.get("ts")
    return {
        "txn_id": _sid(row.get("TransactionID")),
        "card_id": _sid(row.get("card_id")),
        "customer_id": _sid(row.get("customer_id")),
        "amount": float(row.get("TransactionAmt") or 0),
        "ts": ts.isoformat(sep=" ") if isinstance(ts, datetime) else "",
        "channel": _sid(row.get("channel")),
        "product": _sid(row.get("ProductCD")),
        "addr1": _sid(row.get("addr1")),
        "email": _sid(row.get("R_emaildomain") or row.get("P_emaildomain")),
        "risk_score": float(row.get("risk_score") or 0),
        "id_15": _sid(row.get("id_15")),
        "device_profile": _sid(row.get("device_profile")),
    }


@lru_cache(maxsize=1)
def get_store(data_dir: str | None = None) -> CsvGraphStore:
    return CsvGraphStore(Path(data_dir) if data_dir else None)
