from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "safety", "account_security", "gift_failed_live", "payment_issue", "churn_risk",
    "host_conduct", "vip_request", "general_question", "positive_feedback", "noise",
]


class ModelOutput(BaseModel):
    """What the model may return. It never returns a priority."""

    category: Category
    safety_flag: bool = False
    security_flag: bool = False
    churn_signal: bool = False
    mentions_host: str | None = None
    language: str = "en"
    summary: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
