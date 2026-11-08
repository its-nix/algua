"""Append-only experimental evidence, separate from strict forward certificates (v50)."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS experimental_paper_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 deployment_id INTEGER NOT NULL REFERENCES strategy_deployments(id),
 session TEXT NOT NULL,
 account_id TEXT,
 profile_digest TEXT NOT NULL,
 passed INTEGER NOT NULL CHECK(passed IN (0,1)),
 evidence_json TEXT NOT NULL,
 observed_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
);
CREATE INDEX IF NOT EXISTS ix_experimental_sessions_epoch
 ON experimental_paper_sessions(deployment_id,session,id);
CREATE TRIGGER IF NOT EXISTS experimental_sessions_no_update
 BEFORE UPDATE ON experimental_paper_sessions BEGIN
 SELECT RAISE(ABORT,'experimental sessions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS experimental_sessions_no_delete
 BEFORE DELETE ON experimental_paper_sessions BEGIN
 SELECT RAISE(ABORT,'experimental sessions are immutable'); END;
CREATE TABLE IF NOT EXISTS experimental_qualifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 deployment_id INTEGER NOT NULL REFERENCES strategy_deployments(id),
 profile_digest TEXT NOT NULL,
 evidence_digest TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 actor TEXT NOT NULL CHECK(actor='human'),
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
 UNIQUE(deployment_id,profile_digest,evidence_digest)
);
CREATE TRIGGER IF NOT EXISTS experimental_qualifications_no_update
 BEFORE UPDATE ON experimental_qualifications BEGIN
 SELECT RAISE(ABORT,'experimental qualifications are immutable'); END;
CREATE TRIGGER IF NOT EXISTS experimental_qualifications_no_delete
 BEFORE DELETE ON experimental_qualifications BEGIN
 SELECT RAISE(ABORT,'experimental qualifications are immutable'); END;
"""
