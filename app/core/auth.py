import hashlib
import secrets
from eth_account.messages import encode_defunct
from web3 import Web3


def generate_api_key() -> tuple[str, str]:
    """Returns (raw_key, sha256_hash)."""
    raw = "yd_live_" + secrets.token_hex(24)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def generate_api_secret() -> tuple[str, str]:
    """Returns (raw_secret, sha256_hash)."""
    raw = "yd_secret_" + secrets.token_hex(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def generate_session_token() -> str:
    return secrets.token_hex(32)


def generate_nonce() -> str:
    return secrets.token_hex(16)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(raw_key: str) -> str:
    """Displayable prefix like yd_live_a3f8...b9e2"""
    return raw_key[:16] + "..." + raw_key[-4:]


def verify_signature(address: str, message: str, signature: str) -> bool:
    try:
        w3 = Web3()
        msg = encode_defunct(text=message)
        recovered = w3.eth.account.recover_message(msg, signature=signature)
        return recovered.lower() == address.lower()
    except Exception:
        return False


def build_register_message(address: str, nonce: str) -> str:
    return (
        f"Sign this message to register as a Yieldo partner.\n\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}"
    )


def build_login_message(address: str, nonce: str) -> str:
    return (
        f"Sign this message to login to Yieldo partner portal.\n\n"
        f"Address: {address}\n"
        f"Nonce: {nonce}"
    )
