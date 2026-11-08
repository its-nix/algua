"""Distinct human-signed experimental authority; no strict-forward evidence is minted (v52)."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS capped_live_challenges (
 nonce TEXT PRIMARY KEY, strategy_id INTEGER NOT NULL REFERENCES strategies(id),
 context_json TEXT NOT NULL, issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS capped_live_authorizations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 strategy_id INTEGER NOT NULL REFERENCES strategies(id),
 deployment_id INTEGER NOT NULL REFERENCES strategy_deployments(id),
 qualification_id INTEGER NOT NULL REFERENCES experimental_qualifications(id),
 approval_id INTEGER NOT NULL REFERENCES approvals(id),
 risk_policy_id INTEGER NOT NULL REFERENCES drawdown_policies(id),
 prior_authorization_id INTEGER REFERENCES capped_live_authorizations(id),
 capital TEXT NOT NULL, live_account_id TEXT NOT NULL, provider_json TEXT NOT NULL,
 nonce TEXT NOT NULL UNIQUE REFERENCES capped_live_challenges(nonce), expires_at TEXT NOT NULL,
 signature TEXT NOT NULL, principal TEXT NOT NULL, authorized_at TEXT NOT NULL,
 revoked_at TEXT, revocation_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_capped_live_strategy ON capped_live_authorizations(strategy_id,id);
CREATE TRIGGER IF NOT EXISTS capped_live_no_replace BEFORE INSERT ON capped_live_authorizations
 WHEN EXISTS (SELECT 1 FROM capped_live_authorizations
              WHERE id=NEW.id OR nonce=NEW.nonce)
 BEGIN SELECT RAISE(ABORT,'capped live authority cannot be replaced'); END;
CREATE TRIGGER IF NOT EXISTS capped_live_no_delete BEFORE DELETE ON capped_live_authorizations
 BEGIN SELECT RAISE(ABORT,'capped live authority is permanent'); END;
CREATE TRIGGER IF NOT EXISTS capped_live_revoke_only BEFORE UPDATE ON capped_live_authorizations
 WHEN NOT (OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
 AND NEW.id IS OLD.id AND NEW.strategy_id IS OLD.strategy_id
 AND NEW.deployment_id IS OLD.deployment_id AND NEW.qualification_id IS OLD.qualification_id
 AND NEW.approval_id IS OLD.approval_id AND NEW.risk_policy_id IS OLD.risk_policy_id
 AND NEW.prior_authorization_id IS OLD.prior_authorization_id
 AND NEW.capital IS OLD.capital AND NEW.live_account_id IS OLD.live_account_id
 AND NEW.provider_json IS OLD.provider_json AND NEW.nonce IS OLD.nonce
 AND NEW.expires_at IS OLD.expires_at AND NEW.signature IS OLD.signature
 AND NEW.principal IS OLD.principal AND NEW.authorized_at IS OLD.authorized_at)
 BEGIN SELECT RAISE(ABORT,'capped live authority permits only one-way revocation'); END;
"""
