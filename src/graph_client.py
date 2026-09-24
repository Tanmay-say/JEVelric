"""Graph retrieval through TigerGraph MCP, with the CSV dev fallback."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import config
from .csv_store import _public_txn, _sid, get_store

LAST_CALL_COUNT = 0


def _bump(n: int = 1) -> None:
    global LAST_CALL_COUNT
    LAST_CALL_COUNT += n


def _is_tigergraph() -> bool:
    if config.GRAPH_BACKEND not in {"csv", "tigergraph"}:
        raise ValueError("GRAPH_BACKEND must be either 'csv' or 'tigergraph'")
    return config.GRAPH_BACKEND == "tigergraph"


def _mcp():
    return config.get_mcp_client()


def _unwrap_query(value: Any) -> Any:
    if isinstance(value, dict) and "result" in value:
        return value["result"]
    return value


def _walk(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _walk(item)
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from _walk(child)


def _attrs(record: dict, id_key: str) -> dict:
    attrs = record.get("attributes")
    if isinstance(attrs, dict):
        merged = dict(attrs)
        for source_key in ("v_id", "vertex_id", "id"):
            if record.get(source_key) is not None:
                merged.setdefault(id_key, record[source_key])
                break
        return merged
    return record


def _rows(result: Any, id_key: str) -> list[dict]:
    result = _unwrap_query(result)
    found: dict[str, dict] = {}
    for candidate in _walk(result):
        row = _attrs(candidate, id_key)
        value = row.get(id_key)
        if value is not None:
            found[str(value)] = row
    return list(found.values())


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).replace("T", " ").rstrip("Z")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _public_graph_txn(row: dict) -> dict:
    ts = _dt(row.get("ts"))
    return {
        "txn_id": _sid(row.get("txn_id")),
        "card_id": _sid(row.get("card_id")),
        "customer_id": _sid(row.get("customer_id")),
        "amount": _float(row.get("amount")),
        "ts": ts.isoformat(sep=" ") if ts else _sid(row.get("ts")),
        "channel": _sid(row.get("channel")),
        "product": _sid(row.get("product_code")),
        "addr1": _sid(row.get("addr1")),
        "email": _sid(row.get("email")),
        "risk_score": _float(row.get("risk_score")),
        "id_15": _sid(row.get("id_15")),
        "device_profile": _sid(row.get("device_profile")),
    }


def _derive_hints(evidence: dict, flagged_txn_id: str, card_id: str, flagged_raw: dict | None = None) -> dict:
    flagged = evidence.get("flagged") or {}
    window = evidence.get("card_window") or {}
    txns = window.get("txns") or []
    hist = evidence.get("customer_history") or {}
    devices = evidence.get("device_neighbors") or {}
    regions = evidence.get("region_cluster") or {}
    emails = evidence.get("email_cluster") or {}
    small_online = [t for t in txns if t.get("channel") == "online" and _float(t.get("amount")) < 5]
    large = [t for t in txns if _float(t.get("amount")) > 100]
    testing = len(small_online) >= 3 and bool(large)
    id_15 = _sid(flagged.get("id_15")).lower()
    new_device = id_15 == "new"
    channel = _sid(flagged.get("channel"))
    addr1 = _sid(flagged.get("addr1"))
    hist_regions = set(hist.get("regions") or [])
    out_of_region = channel == "in_person" and addr1 and addr1 not in hist_regions and bool(hist_regions)
    mean_amt = _float(hist.get("mean_amt"))
    amount = _float(flagged.get("amount"))
    unusual_amt = mean_amt > 0 and amount > max(50, mean_amt * 3)
    cnp = channel == "online" and (unusual_amt or new_device)
    mixed = set(hist.get("channels") or []) == {"online", "in_person"} and channel == "online"
    takeover = mixed and (new_device or _sid((flagged_raw or {}).get("id_23")).lower() in {"anonymous", "hidden"})
    n_dev, n_reg, n_email = (len(x.get("card_ids") or []) for x in (devices, regions, emails))
    shared_device = 1 <= n_dev <= 20
    shared_region = 2 <= n_reg <= 12
    shared_email = 2 <= n_email <= 12
    exposure = _float(window.get("exposure_usd") or amount)
    evidence_count = 1 + int(shared_device) + int(bool(txns))
    if testing:
        pattern, probability = "card_testing", 0.82
    elif takeover:
        pattern, probability = "account_takeover", 0.74
    elif new_device and cnp:
        pattern, probability = "card_not_present_new_device", 0.68
    elif out_of_region:
        pattern, probability = "out_of_region_use", 0.62
    elif cnp:
        pattern, probability = "card_not_present_fraud", 0.58
    else:
        pattern, probability = "none", 0.28
    if shared_device:
        probability = min(0.95, probability + 0.12)
    confirmed = [
        m for m in ((evidence.get("closed_case_similarity") or {}).get("matches") or [])
        if m.get("outcome") == "confirmed_fraud"
    ]
    return {
        "fraud_probability": round(probability, 4),
        "pattern": pattern,
        "exposure_usd": round(exposure, 2),
        "shared_device_flag": shared_device,
        "shared_region_flag": shared_region,
        "shared_email_flag": shared_email,
        "single_signal_only": not (testing or shared_device or (cnp and new_device) or out_of_region),
        "evidence_count": max(1, min(evidence_count, 4)),
        "evidence_sufficiency": 0.55 if not (testing or shared_device or (cnp and new_device) or out_of_region) else 0.72,
        "undocumented_coordinated": False,
        "dispute_matches_recurring": False,
        "confirmed_cards_count": min(len({m.get("case_id") for m in confirmed}), 3),
        "id_15": _sid(flagged.get("id_15")),
        "channel": channel,
        "amount": amount,
    }


def retrieve_all(card_id: str, customer_id: str, flagged_txn_id: str) -> dict:
    global LAST_CALL_COUNT
    LAST_CALL_COUNT = 0
    if not _is_tigergraph():
        store = get_store()
        flagged = store.by_txn.get(_sid(flagged_txn_id))
        evidence = {
            "card_window": store.card_window(card_id, flagged_txn_id, hours=config.CARD_WINDOW_HOURS),
            "device_neighbors": store.device_neighbors(flagged_txn_id),
            "region_cluster": store.region_cluster(flagged_txn_id, window_days=7),
            "email_cluster": store.email_cluster(flagged_txn_id, window_days=7),
            "closed_case_similarity": store.closed_case_similarity(customer_id, card_id),
            "customer_history": store.customer_history(customer_id),
            "flagged": _public_txn(flagged) if flagged else {},
        }
        evidence["_hints"] = store.derive_hints(evidence, flagged_txn_id, card_id, customer_id)
        LAST_CALL_COUNT = 6
        return evidence

    _bump()
    window, flagged_raw = _fetch_card_window(card_id, config.CARD_WINDOW_HOURS, flagged_txn_id)
    evidence = {
        "card_window": window,
        "device_neighbors": device_neighbors_for_txn(flagged_txn_id),
        "region_cluster": region_cluster_for_txn(flagged_txn_id, 7),
        "email_cluster": email_cluster_for_txn(flagged_txn_id, 7),
        "closed_case_similarity": closed_case_similarity(customer_id, card_id),
        "customer_history": customer_history(customer_id),
    }
    evidence["flagged"] = next(
        (txn for txn in evidence["card_window"].get("txns", []) if txn.get("txn_id") == str(flagged_txn_id)),
        {},
    )
    evidence["_hints"] = _derive_hints(evidence, flagged_txn_id, card_id, flagged_raw)
    return evidence


def card_window(card_id: str, hours: int = 2, flagged_txn_id: str = "") -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().card_window(card_id, flagged_txn_id, hours=hours)
    result, _ = _fetch_card_window(card_id, hours, flagged_txn_id)
    return result


def _fetch_card_window(card_id: str, hours: int, flagged_txn_id: str) -> tuple[dict, dict]:
    raw = _mcp().query("card_window", card_vertex=(card_id,), flagged_vertex=(flagged_txn_id,), hours=hours)
    raw_txns = _rows(raw, "txn_id")
    flagged_raw = next((row for row in raw_txns if str(row.get("txn_id")) == str(flagged_txn_id)), {})
    txns = [_public_graph_txn(row) for row in raw_txns]
    txns.sort(key=lambda x: _dt(x.get("ts")) or datetime.min)
    flagged = next((row for row in txns if row["txn_id"] == str(flagged_txn_id)), None)
    center = _dt(flagged.get("ts")) if flagged else None
    if center:
        txns = [row for row in txns if (ts := _dt(row.get("ts"))) and abs(ts - center) <= timedelta(hours=hours)]
    if flagged and all(t["txn_id"] != flagged["txn_id"] for t in txns):
        txns.append(flagged)
        txns.sort(key=lambda x: _dt(x.get("ts")) or datetime.min)
    ids = [t["txn_id"] for t in txns]
    dates = [(_dt(t["ts"]).strftime("%Y-%m-%d")) for t in txns if _dt(t["ts"])]
    amounts = [_float(t["amount"]) for t in txns]
    claim = (
        f"Card {card_id} has {len(txns)} transaction(s) within ±{hours}h of "
        f"{flagged_txn_id} totaling ${sum(amounts):.2f}."
    ) if flagged else f"Flagged transaction {flagged_txn_id} was not found."
    result = {
        "affected_txn_ids": ids,
        "activity_dates": [dates[0], dates[-1]] if dates else [],
        "txns": txns,
        "claim_text": claim,
    }
    if flagged:
        result["exposure_usd"] = round(sum(amounts), 2)
    return result, flagged_raw


def device_neighbors_for_txn(txn_id: str) -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().device_neighbors(txn_id)
    raw = _mcp().query("device_neighbors", txn_vertex=(txn_id,), window_days=config.SHARED_ORIGIN_WINDOW_DAYS)
    txns = [_public_graph_txn(r) for r in _rows(raw, "txn_id")]
    cards = sorted({r["card_id"] for r in txns if r.get("card_id")})
    if len(cards) > 25:
        return {"card_ids": [], "device_profiles": [], "txns": []}
    profile = next((r.get("device_profile") for r in txns if r.get("device_profile")), "")
    return {"card_ids": cards, "device_profiles": [profile] if cards and profile else [], "txns": txns}


def region_cluster_for_txn(txn_id: str, window_days: int = 7) -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().region_cluster(txn_id, window_days=window_days)
    raw = _mcp().query("region_cluster", txn_vertex=(txn_id,), window_days=window_days)
    txns = [_public_graph_txn(r) for r in _rows(raw, "txn_id")]
    regions = _rows(raw, "addr1")
    result = _cluster_shape(txns, "region", "addr1")
    result["region"] = _sid(regions[0].get("addr1")) if regions else (txns[0].get("addr1", "") if txns else "")
    return result


def email_cluster_for_txn(txn_id: str, window_days: int = 7) -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().email_cluster(txn_id, window_days=window_days)
    raw = _mcp().query("email_cluster", txn_vertex=(txn_id,), window_days=window_days)
    txns = [_public_graph_txn(r) for r in _rows(raw, "txn_id")]
    domains = _rows(raw, "domain")
    result = _cluster_shape(txns, "email", "email")
    result["email"] = _sid(domains[0].get("domain")) if domains else (txns[0].get("email", "") if txns else "")
    return result


def _cluster_shape(txns: list[dict], output_key: str, txn_key: str) -> dict:
    by_card = {}
    for txn in txns:
        card = txn.get("card_id")
        if card:
            by_card[card] = txn
    cards = sorted(by_card)
    primary = next((t.get(txn_key) for t in txns if t.get(txn_key)), "")
    return {"card_ids": cards[:25], output_key: primary, "txns": [by_card[c] for c in cards[:10]]}


def closed_case_similarity(customer_id: str, card_id: str, top_k: int = 5) -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().closed_case_similarity(customer_id, card_id, top_k=top_k)
    raw = _mcp().query("closed_case_similarity", customer_id=customer_id, card_vertex=(card_id,), top_k=top_k)
    matches = []
    for row in _rows(raw, "case_id"):
        score = _float(row.get("score"))
        connected = row.get("connected_card_ids") or ""
        if isinstance(connected, str):
            connected = connected.replace("|", ",").split(",")
        if row.get("customer_id") == customer_id:
            score += 5
        if row.get("card_id") == card_id:
            score += 4
        if card_id in connected:
            score += 3
        notes = _sid(row.get("analyst_notes")).lower()
        if customer_id.lower() in notes or card_id.lower() in notes:
            score += 1
        if score > 0:
            matches.append({
                "case_id": _sid(row.get("case_id")),
                "score": score,
                "pattern": _sid(row.get("pattern")),
                "outcome": _sid(row.get("outcome")),
                "notes": _sid(row.get("analyst_notes"))[:500],
            })
    matches.sort(key=lambda m: m["score"], reverse=True)
    return {"matches": matches[:top_k]}


def customer_history(customer_id: str) -> dict:
    _bump()
    if not _is_tigergraph():
        return get_store().customer_history(customer_id)
    raw = _mcp().query("customer_history", customer_vertex=(customer_id,), days=config.CUSTOMER_HISTORY_DAYS)
    rows = [_public_graph_txn(r) for r in _rows(raw, "txn_id")]
    rows.sort(key=lambda x: _dt(x.get("ts")) or datetime.min)
    stamped = [(row, _dt(row.get("ts"))) for row in rows]
    latest = max((ts for _, ts in stamped if ts is not None), default=None)
    if latest:
        cutoff = latest - timedelta(days=config.CUSTOMER_HISTORY_DAYS)
        rows = [row for row, ts in stamped if ts is not None and ts >= cutoff]
    amounts = [_float(r.get("amount")) for r in rows]
    return {
        "txns": rows[-40:],
        "regions": sorted({r["addr1"] for r in rows if r.get("addr1")}),
        "products": sorted({r["product"] for r in rows if r.get("product")}),
        "channels": sorted({r["channel"] for r in rows if r.get("channel")}),
        "card_ids": sorted({r["card_id"] for r in rows if r.get("card_id")}),
        "mean_amt": round(sum(amounts) / len(amounts), 2) if amounts else 0.0,
        "n": len(rows),
    }


def write_case(case, case_id: str, customer_id: str = "") -> str:
    _bump()
    if not _is_tigergraph():
        return get_store().write_case(case, case_id)
    client = _mcp()
    graph_case_id = f"G-{case_id}"
    attrs = {
        "case_id": case_id,
        "customer_id": customer_id,
        "status": getattr(case.status, "value", case.status),
        "verdict": getattr(case.verdict, "value", case.verdict),
        "fraud_probability": case.fraud_probability,
        "pattern": getattr(case.pattern, "value", case.pattern),
        "exposure_usd": case.exposure_usd,
        "summary": case.summary,
    }
    client.call_tool("tigergraph__add_node", {
        "graph_name": config.TG_GRAPH_NAME,
        "vertex_type": "InvestigationCase",
        "vertex_id": graph_case_id,
        "attributes": attrs,
    })
    _add_edges(client, "INVESTIGATES", "Transaction", [
        (graph_case_id, txn) for txn in case.affected_txn_ids
    ])
    primary_card_id = getattr(case, "_primary_card_id", "")
    _add_edges(client, "CASE_ON_CARD", "Card", [
        (graph_case_id, card) for card in sorted(set(case.connected_card_ids + [primary_card_id]))
    ])
    _add_edges(client, "CITES", "ClosedCase", [(graph_case_id, prior) for prior in case.similar_prior_cases])
    _add_edges(client, "CASE_FROM_DEVICE", "DeviceProfile", [(graph_case_id, profile) for profile in case.connected_device_profiles])
    return graph_case_id


def _add_edges(client, edge_type: str, target_type: str, pairs: list[tuple[str, str]]) -> None:
    pairs = [(source, target) for source, target in pairs if source and target]
    if not pairs:
        return
    _bump()
    client.call_tool("tigergraph__add_edges", {
        "graph_name": config.TG_GRAPH_NAME,
        "edge_type": edge_type,
        "edges": [
            {"source_id": source, "target_id": target, "source_type": "InvestigationCase", "target_type": target_type}
            for source, target in pairs
        ],
    })


def known_ids_for(card_id: str, customer_id: str) -> set[str]:
    if not _is_tigergraph():
        return get_store().known_ids_for(card_id, customer_id)
    _bump()
    raw = _mcp().query(
        "known_ids_for", customer_id=customer_id, card_vertex=(card_id,), customer_vertex=(customer_id,)
    )
    ids: set[str] = set()
    for field in ("customer_id", "card_id", "txn_id", "device_profile_id", "device_profile", "case_id", "graph_case_id"):
        for row in _rows(raw, field):
            value = row.get(field)
            if value:
                ids.add(str(value))
    # Do not bless the intake keys without a graph result; only observed graph
    # identifiers can satisfy answer-file entity validation on the TG backend.
    return ids
