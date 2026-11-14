"""Signed account policies, durable independent risk state and immutable evidence (v51)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS drawdown_policies (
 id INTEGER PRIMARY KEY AUTOINCREMENT, lane TEXT NOT NULL CHECK(lane IN ('paper','live')),
 account_id TEXT NOT NULL, policy_json TEXT NOT NULL, principal TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drawdown_accounts (
 lane TEXT PRIMARY KEY CHECK(lane IN ('paper','live')), account_id TEXT NOT NULL,
 policy_id INTEGER NOT NULL REFERENCES drawdown_policies(id), revision INTEGER NOT NULL,
 state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drawdown_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, lane TEXT NOT NULL, account_id TEXT NOT NULL,
 policy_id INTEGER NOT NULL REFERENCES drawdown_policies(id), kind TEXT NOT NULL,
 state_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drawdown_challenges (
 nonce TEXT PRIMARY KEY, purpose TEXT NOT NULL, lane TEXT NOT NULL, account_id TEXT NOT NULL,
 options_json TEXT NOT NULL, request_json TEXT NOT NULL, issued_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS drawdown_reductions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, lane TEXT NOT NULL, account_id TEXT NOT NULL,
 policy_id INTEGER NOT NULL REFERENCES drawdown_policies(id), strategy TEXT NOT NULL,
 symbol TEXT NOT NULL, qty TEXT NOT NULL, limit_price TEXT NOT NULL,
 client_order_id TEXT NOT NULL UNIQUE,
 broker_order_id TEXT, phase TEXT NOT NULL DEFAULT 'prepared'
 CHECK(phase IN ('prepared','submitting','sent','not_submitted')),
 created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS drawdown_policy_immutable_update BEFORE UPDATE ON drawdown_policies
 BEGIN SELECT RAISE(ABORT,'drawdown policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_policy_immutable_delete BEFORE DELETE ON drawdown_policies
 BEGIN SELECT RAISE(ABORT,'drawdown policy is immutable'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_events_immutable_update BEFORE UPDATE ON drawdown_events
 BEGIN SELECT RAISE(ABORT,'drawdown events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_events_immutable_delete BEFORE DELETE ON drawdown_events
 BEGIN SELECT RAISE(ABORT,'drawdown events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_account_no_delete BEFORE DELETE ON drawdown_accounts
 BEGIN SELECT RAISE(ABORT,'drawdown account cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_reduction_request_immutable
 BEFORE UPDATE ON drawdown_reductions
 WHEN NEW.lane IS NOT OLD.lane OR NEW.account_id IS NOT OLD.account_id
 OR NEW.policy_id IS NOT OLD.policy_id OR NEW.strategy IS NOT OLD.strategy
 OR NEW.symbol IS NOT OLD.symbol OR NEW.qty IS NOT OLD.qty
 OR NEW.limit_price IS NOT OLD.limit_price OR NEW.client_order_id IS NOT OLD.client_order_id
 OR NEW.created_at IS NOT OLD.created_at
 OR (OLD.broker_order_id IS NOT NULL AND NEW.broker_order_id IS NOT OLD.broker_order_id)
 BEGIN SELECT RAISE(ABORT,'reduction request is immutable'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_reduction_phase
 BEFORE UPDATE ON drawdown_reductions
 WHEN NOT (NEW.phase IS OLD.phase
 OR (OLD.phase='prepared' AND NEW.phase IN ('submitting','not_submitted'))
 OR (OLD.phase='submitting' AND NEW.phase='sent'))
 BEGIN SELECT RAISE(ABORT,'invalid reduction phase transition'); END;
CREATE TRIGGER IF NOT EXISTS drawdown_reduction_no_delete BEFORE DELETE ON drawdown_reductions
 BEGIN SELECT RAISE(ABORT,'reduction request is immutable'); END;
CREATE INDEX IF NOT EXISTS ix_drawdown_events_lane ON drawdown_events(lane,id);
"""
