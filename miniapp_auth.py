import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_admin_token(secret: str, admin_id: int, ttl_minutes: int) -> str:
    exp = int(time.time()) + max(1, ttl_minutes) * 60
    payload = {"admin_id": admin_id, "exp": exp}
    payload_raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_part = _b64url_encode(payload_raw)

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_part = _b64url_encode(signature)
    return f"{payload_part}.{signature_part}"


def verify_admin_token(secret: str, token: str) -> int | None:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_part.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    try:
        provided_signature = _b64url_decode(signature_part)
    except Exception:
        return None

    if not hmac.compare_digest(expected_signature, provided_signature):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception:
        return None

    exp = int(payload.get("exp", 0))
    admin_id = int(payload.get("admin_id", 0))
    if exp < int(time.time()) or admin_id <= 0:
        return None

    return admin_id


def verify_telegram_init_data(bot_token: str, init_data: str) -> tuple[int, str] | None:
    if not init_data:
        return None

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    user_raw = pairs.get("user", "")
    if not user_raw:
        return None

    try:
        user = json.loads(user_raw)
        user_id = int(user.get("id", 0))
        username = str(user.get("username", "")).strip().lower()
    except Exception:
        return None

    if user_id <= 0:
        return None

    return user_id, username
