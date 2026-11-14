from __future__ import annotations

# Minimum holdout sample (Wall C). A holdout with fewer observations is underpowered and fails
# closed — complements the 1/sqrt(T) haircut, which is ZERO at N=1. ~one trading quarter. Protected
#
# Consumed by the gate criteria (``gates.GateCriteria`` default). Kept in this pure leaf so any
# research module can reference it without importing ``gates``.
MIN_HOLDOUT_OBSERVATIONS = 63
