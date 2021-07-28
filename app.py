import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

DB_PATH = os.environ.get("RECON_DB", "reconcile.db")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "dev_secret_key_change_me")

app = FastAPI(title="Webhook & Payment Reconciler")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            idempotency_key TEXT PRIMARY KEY,
            tx_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_entries (
            tx_id TEXT PRIMARY KEY,
            amount_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            last_event_time TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def log_audit(conn: sqlite3.Connection, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_logs (action, detail, created_at) VALUES (?, ?, ?)",
        (action, detail, datetime.utcnow().isoformat()),
    )


def verify_sig(raw_body: bytes, sig_header: Optional[str]) -> bool:
    if not sig_header:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.strip())


class SettlementItem(BaseModel):
    tx_id: str
    settled_cents: int
    currency: str = "USD"


class ReconcileRequest(BaseModel):
    settlements: List[SettlementItem]


@app.post("/webhooks/payment")
async def ingest_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None),
) -> Dict:
    raw = await request.body()
    if not verify_sig(raw, x_signature):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="missing Idempotency-Key header")

    payload = json.loads(raw.decode("utf-8"))
    tx_id = payload["tx_id"]
    event_type = payload["event_type"]
    event_time = payload["event_time"]
    amount_cents = int(payload["amount_cents"])
    currency = payload.get("currency", "USD")

    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT idempotency_key FROM webhook_events WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            log_audit(conn, "duplicate_ignored", "key=%s tx=%s" % (idempotency_key, tx_id))
            conn.commit()
            return {"status": "duplicate_ignored", "idempotency_key": idempotency_key}

        conn.execute(
            """
            INSERT INTO webhook_events (idempotency_key, tx_id, event_type, event_time, payload_json, received_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (idempotency_key, tx_id, event_type, event_time, raw.decode("utf-8"), datetime.utcnow().isoformat()),
        )

        # handle out-of-order events by comparing event_time
        ledger = conn.execute(
            "SELECT last_event_time, status FROM ledger_entries WHERE tx_id = ?", (tx_id,)
        ).fetchone()

        if ledger is None:
            conn.execute(
                """
                INSERT INTO ledger_entries (tx_id, amount_cents, currency, status, last_event_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tx_id, amount_cents, currency, event_type, event_time),
            )
            log_audit(conn, "ledger_created", "tx=%s status=%s" % (tx_id, event_type))
        elif event_time >= ledger["last_event_time"]:
            conn.execute(
                """
                UPDATE ledger_entries SET amount_cents = ?, status = ?, last_event_time = ?
                WHERE tx_id = ?
                """,
                (amount_cents, event_type, event_time, tx_id),
            )
            log_audit(conn, "ledger_updated", "tx=%s status=%s" % (tx_id, event_type))
