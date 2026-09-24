from src import config, graph_client
from src.mcp_client import TigerGraphMCPClient


class FakeMCP:
    def __init__(self):
        self.calls = []

    def query(self, name, **params):
        self.calls.append((name, params))
        if name == "card_window":
            return [
                {"txn_id": "TX-1", "card_id": "C-1", "customer_id": "U-1", "ts": "2024-01-01 10:00:00", "amount": 12},
                {"txn_id": "TX-2", "card_id": "C-1", "customer_id": "U-1", "ts": "2024-01-01 10:30:00", "amount": 20, "id_23": "anonymous"},
            ]
        if name in {"device_neighbors", "region_cluster", "email_cluster"}:
            return []
        if name == "closed_case_similarity":
            return []
        if name == "customer_history":
            return [{"txn_id": "TX-1", "card_id": "C-1", "customer_id": "U-1", "ts": "2024-01-01 10:00:00", "amount": 12}]
        raise AssertionError(name)


def test_tigergraph_retrieval_uses_mcp_without_csv(monkeypatch):
    fake = FakeMCP()
    monkeypatch.setattr(config, "GRAPH_BACKEND", "tigergraph")
    monkeypatch.setattr(graph_client, "_mcp", lambda: fake)
    monkeypatch.setattr(graph_client, "get_store", lambda: (_ for _ in ()).throw(AssertionError("CSV used")))

    evidence = graph_client.retrieve_all("C-1", "U-1", "TX-2")

    assert [name for name, _ in fake.calls] == [
        "card_window", "device_neighbors", "region_cluster", "email_cluster",
        "closed_case_similarity", "customer_history",
    ]
    assert evidence["card_window"]["affected_txn_ids"] == ["TX-1", "TX-2"]
    assert evidence["card_window"]["exposure_usd"] == 32
    assert evidence["flagged"]["txn_id"] == "TX-2"
    assert evidence["customer_history"]["n"] == 1
    assert graph_client.LAST_CALL_COUNT == 6


def test_tigergraph_configuration_gate(monkeypatch):
    monkeypatch.setattr(config, "TG_HOST", "")
    monkeypatch.setattr(config, "TG_SECRET", "")
    config.get_mcp_client.cache_clear()
    try:
        try:
            config.get_mcp_client()
        except RuntimeError as exc:
            assert "TG_HOST and TG_SECRET" in str(exc)
        else:
            raise AssertionError("missing credentials should fail clearly")
    finally:
        config.get_mcp_client.cache_clear()


def test_mcp_client_decodes_formatted_success_and_errors():
    from types import SimpleNamespace

    ok = SimpleNamespace(
        isError=False,
        structuredContent=None,
        content=[SimpleNamespace(text='```json\n{"success":true,"data":{"count":590742}}\n```')],
    )
    assert TigerGraphMCPClient._decode(ok) == {"count": 590742}

    failed = SimpleNamespace(
        isError=False,
        structuredContent=None,
        content=[SimpleNamespace(text='```json\n{"success":false,"error":"denied"}\n```')],
    )
    try:
        TigerGraphMCPClient._decode(failed)
    except RuntimeError as exc:
        assert "denied" in str(exc)
    else:
        raise AssertionError("formatted MCP tool errors must raise")


def test_known_ids_for_queries_live_related_ids(monkeypatch):
    fake = FakeMCP()
    fake.query = lambda name, **params: {
        "result": {
            "Customers": [{"customer_id": "U-1"}],
            "Cards": [{"card_id": "C-1"}],
            "Transactions": [{"txn_id": "TX-1"}],
            "Devices": [{"device_profile_id": "D-1"}],
            "CustomerCases": [{"case_id": "CC-1"}],
            "InvestigationCases": [{"graph_case_id": "G-HHG-017", "case_id": "HHG-017"}],
        }
    }
    monkeypatch.setattr(config, "GRAPH_BACKEND", "tigergraph")
    monkeypatch.setattr(graph_client, "_mcp", lambda: fake)

    ids = graph_client.known_ids_for("C-1", "U-1")

    assert {"U-1", "C-1", "TX-1", "D-1", "CC-1", "HHG-017", "G-HHG-017"} <= ids


def test_write_case_uses_schema_vertex_and_edges(monkeypatch):
    from src.state import Case, CaseStatus, Pattern, Verdict

    class WriteFake(FakeMCP):
        def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"success": True}

    fake = WriteFake()
    monkeypatch.setattr(config, "GRAPH_BACKEND", "tigergraph")
    monkeypatch.setattr(config, "TG_GRAPH_NAME", "HHGOA")
    monkeypatch.setattr(graph_client, "_mcp", lambda: fake)
    case = Case(
        status=CaseStatus.closed_fraud,
        verdict=Verdict.fraud,
        fraud_probability=0.9,
        pattern=Pattern.card_testing,
        affected_txn_ids=["TX-1"],
        connected_card_ids=["C-2"],
        connected_device_profiles=["device-profile-1"],
        similar_prior_cases=["CC-1"],
        summary="Verified test case",
    )
    case._primary_card_id = "C-1"

    graph_case_id = graph_client.write_case(case, "HHG-017", "U-1")

    assert graph_case_id == "G-HHG-017"
    add_node = fake.calls[0]
    assert add_node[0] == "tigergraph__add_node"
    assert add_node[1]["vertex_type"] == "InvestigationCase"
    edge_calls = [args for name, args in fake.calls if name == "tigergraph__add_edges"]
    assert {call["edge_type"] for call in edge_calls} == {
        "INVESTIGATES", "CASE_ON_CARD", "CITES", "CASE_FROM_DEVICE"
    }
    assert all(edge["source_type"] == "InvestigationCase" for call in edge_calls for edge in call["edges"])
