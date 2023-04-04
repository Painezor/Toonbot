"""Credentials file."""
import json

with open("credentials.json", encoding="utf-8") as f:
    _credentials = json.load(f)

__all__ = ["WG_ID"]

WG_ID: str = _credentials["Wargaming"]["client_id"]
