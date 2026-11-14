from __future__ import annotations

# Minimum holdout sample (Wall C). A holdout with fewer observations is underpowered and fails
# closed (a BINDING check). ~one trading quarter. Protected — relaxing it weakens the gate.
#
# Consumed by the gate criteria (``gates.GateCriteria`` default). Kept in this pure leaf so any
# research module can reference it without importing ``gates``.
MIN_HOLDOUT_OBSERVATIONS = 63
