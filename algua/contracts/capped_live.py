"""Pure row-bound experimental authority token; construction itself grants no authority."""

from dataclasses import dataclass

from algua.contracts.types import LiveAuthorization


@dataclass(frozen=True)
class CappedLiveAuthorization(LiveAuthorization):
    authorization_id: int
    deployment_id: int
    approval_id: int
    qualification_id: int
    risk_policy_id: int
    account_id: str
    capital: str
    provider_digest: str
