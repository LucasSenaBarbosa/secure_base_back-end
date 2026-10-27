import base64
import hashlib
import hmac
import json
import secrets
import time
from uuid import UUID

from config.settings import Settings
from shared.errors.problem_details import Problem

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 64
_DUMMY_PASSWORD_HASH = hashlib.scrypt(
    b"securebase-invalid-password",
    salt=b"securebase-dummy-salt",
    n=_SCRYPT_N,
    r=_SCRYPT_R,
    p=_SCRYPT_P,
    dklen=_SCRYPT_LENGTH,
).hex()
_JWT_ISSUER = "securebase-api"
_JWT_AUDIENCE = "securebase-client"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64url(salt)}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if encoded is None:
        hashlib.scrypt(
            password.encode("utf-8"),
            salt=b"securebase-dummy-salt",
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_SCRYPT_LENGTH,
        )
        return False
    try:
        algorithm, n, r, p, encoded_salt, encoded_digest = encoded.split("$")
        if (
            algorithm != "scrypt"
            or int(n) != _SCRYPT_N
            or int(r) != _SCRYPT_R
            or int(p) != _SCRYPT_P
        ):
            raise ValueError
        salt = _b64url_decode(encoded_salt)
        expected = bytes.fromhex(encoded_digest)
        if len(salt) != 16 or len(expected) != _SCRYPT_LENGTH:
            raise ValueError
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise Problem(
            503,
            "INVALID_PASSWORD_HASH",
            "Serviço temporariamente indisponível",
            "Não foi possível validar as credenciais armazenadas.",
        ) from exc
    return hmac.compare_digest(actual, expected)


def issue_access_token(
    settings: Settings,
    user_id: UUID,
    auth_version: int,
    session_id: UUID,
) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + settings.jwt_expiry_seconds
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "sub": str(user_id),
        "iat": now,
        "exp": expires_at,
        "ver": auth_version,
        "sid": str(session_id),
    }
    signing_input = f"{_b64json(header)}.{_b64json(payload)}"
    signature = hmac.new(
        settings.jwt_secret_key.get_secret_value().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url(signature)}", settings.jwt_expiry_seconds


def issue_refresh_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_access_token(settings: Settings, token: str) -> tuple[UUID, int, UUID]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}"
        expected_signature = hmac.new(
            settings.jwt_secret_key.get_secret_value().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(
            _b64url_decode(encoded_signature),
            expected_signature,
        ):
            raise ValueError
        header = json.loads(_b64url_decode(encoded_header))
        payload = json.loads(_b64url_decode(encoded_payload))
        now = int(time.time())
        if (
            not isinstance(header, dict)
            or header.get("alg") != "HS256"
            or header.get("typ") != "JWT"
            or not isinstance(payload, dict)
            or payload.get("iss") != _JWT_ISSUER
            or payload.get("aud") != _JWT_AUDIENCE
            or not isinstance(payload.get("exp"), int)
            or payload["exp"] <= now
            or not isinstance(payload.get("iat"), int)
            or payload["iat"] > now
            or not isinstance(payload.get("ver"), int)
            or not isinstance(payload.get("sid"), str)
        ):
            raise ValueError
        return UUID(payload["sub"]), payload["ver"], UUID(payload["sid"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise Problem(
            401,
            "INVALID_ACCESS_TOKEN",
            "Não autenticado",
            "A sessão é inválida ou expirou.",
        ) from exc


def _b64json(value: dict[str, str | int]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
