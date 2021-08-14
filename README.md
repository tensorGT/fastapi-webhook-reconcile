# fastapi-webhook-reconcile

small backend with FastAPI and SQLite for learn how payment webhooks, idempotency keys, and HMAC signature check work.

## features
- verify `X-Signature` HMAC-SHA256 before saving anything
- check `Idempotency-Key` so duplicate webhook delivery dont double-count
- handle out-of-order events by comparing `event_time`
- `/reconcile` endpoint to compare ledger rows against external settlement list
- `/audit-logs` endpoint for see everything that happened

## run
```bash
pip install -r requirements.txt
uvicorn app:app --reload
```
