"""
InvestigationState + answer-file schema.

Field names, enums, and structure are copied verbatim from the dataset
README's "Answer Format" section. Do not rename fields — they are graded
by exact key match. `InvestigationState` is the working object threaded
through the orchestrator (plan.md §5); `.to_answer()` produces the graded
JSON with (almost) no translation, by design.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


# --------------------------------------------------------------------------
# Enums — exact allowed values from the README. Never widen these.
# --------------------------------------------------------------------------

class TriggerType(str, Enum):
    risk_score = "risk_score"
    customer_report = "customer_report"
    analyst_request = "analyst_request"


class CaseStatus(str, Enum):
    open = "open"
    closed_fraud = "closed_fraud"
    closed_legitimate = "closed_legitimate"
    escalated = "escalated"


class Verdict(str, Enum):
    fraud = "fraud"
    legitimate = "legitimate"
    uncertain = "uncertain"


class Pattern(str, Enum):
    card_testing = "card_testing"
    card_not_present_fraud = "card_not_present_fraud"
    card_not_present_new_device = "card_not_present_new_device"
    out_of_region_use = "out_of_region_use"
    account_takeover = "account_takeover"
    undocumented = "undocumented"
    none = "none"


class EvidenceSource(str, Enum):
    graph = "graph"
    document = "document"
    customer = "customer"
    external = "external"


class EvidenceRequestType(str, Enum):
    customer_validation = "customer_validation"
    step_up_auth = "step_up_auth"
    analyst_info = "analyst_info"


class ApprovalRoute(str, Enum):
    auto = "auto"
    L1 = "L1"
    L2 = "L2"


class Action(str, Enum):
    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class CustomerResponse(str, Enum):
    denied = "denied"
    confirmed = "confirmed"
    no_reply = "no_reply"
    none_requested = "none_requested"


# --------------------------------------------------------------------------
# Answer-file sub-objects (README "Fields" section)
# --------------------------------------------------------------------------

class EvidenceRequest(BaseModel):
    type: EvidenceRequestType
    asked_after_step: int
    assumed_response: str


class RecommendedAction(BaseModel):
    action: Action
    route: ApprovalRoute
    reason: str  # must cite the policy rule, e.g. "R2 and R5: ..."


class NextBestActions(BaseModel):
    initial: list[RecommendedAction] = Field(default_factory=list)
    final: list[RecommendedAction] = Field(default_factory=list)
    what_changed: str = "nothing"


class EvidenceItem(BaseModel):
    claim: str
    source: EvidenceSource
    ref: str
    entity_ids: list[str] = Field(default_factory=list)


class SAR(BaseModel):
    file: bool
    reason: str
    narrative: str = ""
    subjects: list[str] = Field(default_factory=list)
    total_amount_usd: float = 0
    activity_dates: list[str] = Field(default_factory=list)  # ["YYYY-MM-DD", "YYYY-MM-DD"]


class Case(BaseModel):
    _primary_card_id: str = PrivateAttr(default="")

    status: CaseStatus
    verdict: Verdict
    fraud_probability: float = Field(ge=0, le=1)
    pattern: Pattern
    pattern_description: str = ""  # required (non-empty) iff pattern == undocumented
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)
    exposure_usd: float = 0
    evidence: list[EvidenceItem] = Field(default_factory=list)
    similar_prior_cases: list[str] = Field(default_factory=list)
    summary: str
    written_to_graph: bool = False
    graph_case_id: str = ""


class Answer(BaseModel):
    """Exact top-level shape of cases/<case_id>.json."""
    case_id: str
    case: Case
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions
    sar: SAR
    stop_reason: str
    tool_calls: int = 0
    tokens: int = 0
    latency_s: float = 0.0


# --------------------------------------------------------------------------
# Working state — plan.md §5. Not graded directly; feeds Answer.
# --------------------------------------------------------------------------

class Signals(BaseModel):
    """Output of JEV_ASSESS (or the LLM-only fallback). Policy engine input."""
    fraud_probability: float = 0.0
    pattern: Pattern = Pattern.none
    evidence_count: int = 0
    single_signal_only: bool = True
    exposure_usd: float = 0.0
    shared_device_flag: bool = False
    shared_region_flag: bool = False
    shared_email_flag: bool = False
    customer_response: CustomerResponse = CustomerResponse.none_requested
    dispute_matches_recurring: bool = False
    undocumented_coordinated: bool = False
    confirmed_cards_count: int = 0
    evidence_sufficiency: float = 0.0


class InvestigationState(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    trigger_type: TriggerType
    trigger_text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    risk_score: Optional[float] = None  # context only — never copied into fraud_probability

    round: int = 0
    graph_evidence: dict = Field(default_factory=dict)
    graphrag_context: str = ""

    signals: Signals = Field(default_factory=Signals)

    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions = Field(default_factory=NextBestActions)
    sar: Optional[SAR] = None
    case: Optional[Case] = None
    stop_reason: str = ""

    tool_calls: int = 0
    tokens: int = 0
    latency_s: float = 0.0

    def to_answer(self) -> Answer:
        assert self.case is not None and self.sar is not None, "case/sar not assembled yet"
        return Answer(
            case_id=self.case_id,
            case=self.case,
            evidence_requests=self.evidence_requests,
            next_best_actions=self.next_best_actions,
            sar=self.sar,
            stop_reason=self.stop_reason,
            tool_calls=self.tool_calls,
            tokens=self.tokens,
            latency_s=self.latency_s,
        )
