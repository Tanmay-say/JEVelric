"""Smoke-test the configured Cloudflare embedding endpoint on one corpus text."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
token = os.getenv("CF_API_TOKEN", "").strip()
account = os.getenv("CF_ACCOUNT_ID", "").strip()
if not token or not account:
    raise SystemExit("CF_API_TOKEN and CF_ACCOUNT_ID must be set")

with (ROOT / "data" / "grip_corpus" / "documents.jsonl").open(encoding="utf-8") as handle:
    first = json.loads(next(handle))
client = OpenAI(
    api_key=token,
    base_url=f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
    timeout=60.0,
)
response = client.embeddings.create(
    model="@cf/baai/bge-base-en-v1.5",
    input=first["abstract"],
)
vector = response.data[0].embedding
if len(vector) != 768 or not all(isinstance(v, (int, float)) for v in vector):
    raise SystemExit(f"Unexpected embedding shape/type: dimension={len(vector)}")
print(json.dumps({"model": response.model, "dimension": len(vector), "nonzero": any(vector)}, indent=2))
