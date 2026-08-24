"""
SQLite storage layer for Incident Vault.

Note: on Streamlit Community Cloud, the filesystem resets whenever the app
is redeployed (new push) and sometimes after a long sleep/wake cycle. SQLite
is great for a local prototype or a single always-on container, but if you
need data to survive redeploys, swap this module for an external database
(e.g. Supabase/Postgres, Google Sheets, or a hosted SQLite like Turso).
"""

import sqlite3
import time
import uuid
from contextlib import contextmanager

DB_PATH = "vault.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                incident_id TEXT,
                body TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                doc_id TEXT,
                doc_title TEXT NOT NULL,
                approver1_email TEXT NOT NULL,
                approver2_email TEXT NOT NULL,
                step1_status TEXT NOT NULL DEFAULT 'pending',
                step2_status TEXT NOT NULL DEFAULT 'waiting',
                created_at REAL NOT NULL
            )
            """
        )


# --- documents ---------------------------------------------------------

def add_document(title, incident_id, body, upload_bytes=None, upload_filename=None):
    # upload_bytes/upload_filename are accepted for interface parity with the
    # SharePoint backend (which stores the raw file in a document library)
    # but aren't used here — SQLite mode only stores the extracted text.
    doc_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO documents (id, title, incident_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (doc_id, title, incident_id, body, time.time()),
        )
    return doc_id


def get_documents():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# --- approvals -----------------------------------------------------------

def start_approval(doc_id, doc_title, approver1_email, approver2_email):
    approval_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO approvals
                (id, doc_id, doc_title, approver1_email, approver2_email, step1_status, step2_status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 'waiting', ?)
            """,
            (approval_id, doc_id, doc_title, approver1_email, approver2_email, time.time()),
        )
    return approval_id


def get_approvals():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_approval_step(approval_id, step, decision):
    with get_conn() as conn:
        if step == 1:
            next_step2 = "pending" if decision == "approved" else "waiting"
            conn.execute(
                "UPDATE approvals SET step1_status = ?, step2_status = ? WHERE id = ?",
                (decision, next_step2, approval_id),
            )
        else:
            conn.execute(
                "UPDATE approvals SET step2_status = ? WHERE id = ?",
                (decision, approval_id),
            )


def delete_approval(approval_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM approvals WHERE id = ?", (approval_id,))
