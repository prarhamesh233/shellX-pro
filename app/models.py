from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Result = Literal["Pass", "Partial", "Flag", "N/A"]


class Intake(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    domain: Optional[str] = None
    gstin: Optional[str] = None
    director: Optional[str] = None
    declared_turnover: Optional[float] = Field(default=None, ge=0)
    turnover_currency: Literal["INR", "USD"] = "INR"
    declared_headcount: Optional[int] = Field(default=None, ge=0)
    country: str = "India"
    business_type: Literal["b2b", "consumer", "platform", "trading", "other"] = "b2b"
    stated_business: Optional[str] = None
    contact_email: Optional[str] = None
    claims_funding: bool = False
    crustdata_company_id: Optional[int] = None  # set when the user picks a candidate

    @field_validator("domain")
    @classmethod
    def _dom(cls, v):
        if not v:
            return None
        v = v.strip().lower()
        for p in ("https://", "http://"):
            if v.startswith(p):
                v = v[len(p):]
        v = v.split("/")[0]
        if v.startswith("www."):
            v = v[4:]
        return v or None

    @field_validator("gstin", "director", "contact_email", "stated_business")
    @classmethod
    def _blank(cls, v):
        return v.strip() if v and v.strip() else None

    def turnover_usd(self) -> Optional[float]:
        from .config import INR_PER_USD
        if self.declared_turnover is None:
            return None
        return self.declared_turnover / INR_PER_USD if self.turnover_currency == "INR" else self.declared_turnover


class CheckOutcome(BaseModel):
    id: str
    result: Optional[Result] = None          # None = unverifiable / not yet assessed
    value: Optional[str] = None              # short observed value
    evidence: str = ""                       # what we saw, where
    source: str = ""                         # source family
    source_url: Optional[str] = None
    reliability: float = 0.0                 # 0..1 trust in the source for this check
    automated: bool = True
    analyst: bool = False                    # set by a human in the UI
    ts: Optional[str] = None


class LLMSummary(BaseModel):
    summary: str
    innocent_explanations: list[str] = []
    key_concerns: list[str] = []
    analyst_questions: list[str] = []


class Disambiguation(BaseModel):
    chosen_index: Optional[int] = None
    confidence: float = 0.0
    reason: str = ""


class HeadlineVerdict(BaseModel):
    index: int
    relation: Literal["accused", "victim", "unrelated", "neutral"]


class HeadlineClassification(BaseModel):
    items: list[HeadlineVerdict] = []
