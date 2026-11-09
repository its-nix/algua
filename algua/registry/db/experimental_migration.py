"""v53 qualification authorship migration, preserving immutable rows and live references."""
from __future__ import annotations

import re
import sqlite3


def widen_qualification_actors(conn: sqlite3.Connection) -> None:
    """Rebuild SQLite's old human-only CHECK atomically, with FK enforcement restored.

    Do not rename the old table: SQLite would rewrite capped-live foreign keys to the
    temporary name. Disable FK enforcement outside the transaction, swap the replacement
    into the original name, then check references before committing. Writers must be quiesced.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                       "AND name='experimental_qualifications'").fetchone()
    if row is None:
        return
    old = row['sql']
    ddl, changed = re.subn(r"CHECK\s*\(\s*actor\s*=\s*'human'\s*\)",
                          "CHECK(actor IN ('human','agent','system'))", old, flags=re.I)
    if not changed:
        return
    if conn.in_transaction:
        raise ValueError('qualification schema migration requires its own transaction')
    ddl = re.sub(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?experimental_qualifications',
                 'CREATE TABLE experimental_qualifications__v53', ddl, count=1, flags=re.I)
    foreign_keys = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    conn.execute('PRAGMA foreign_keys=OFF')
    try:
        conn.execute('BEGIN IMMEDIATE')
        objects = conn.execute("SELECT sql FROM sqlite_master WHERE "
            "tbl_name='experimental_qualifications' AND type IN ('index','trigger') "
            'AND sql IS NOT NULL').fetchall()
        sequence = conn.execute("SELECT seq FROM sqlite_sequence "
                                "WHERE name='experimental_qualifications'").fetchone()
        conn.execute(ddl)
        conn.execute('INSERT INTO experimental_qualifications__v53 '
                     'SELECT * FROM experimental_qualifications')
        conn.execute('DROP TABLE experimental_qualifications')
        conn.execute('ALTER TABLE experimental_qualifications__v53 '
                     'RENAME TO experimental_qualifications')
        for obj in objects:
            conn.execute(obj['sql'])
        if sequence is not None:
            conn.execute("UPDATE sqlite_sequence SET seq=? "
                         "WHERE name='experimental_qualifications'", (sequence['seq'],))
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('qualification migration found invalid foreign keys')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute(f'PRAGMA foreign_keys={foreign_keys}')
