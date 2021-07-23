# fastapi-webhook-reconcile

small backend with FastAPI and SQLite for learn how payment webhooks, idempotency keys, and HMAC signature check work.

## features
- verify `X-Signature` HMAC-SHA256 before saving anything
- check `Idempotency-Key` so duplicate webhook delivery dont double-count
