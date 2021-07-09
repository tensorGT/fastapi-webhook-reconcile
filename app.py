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
