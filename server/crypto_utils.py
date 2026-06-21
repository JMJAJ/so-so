"""
Simple encryption for API keys stored in the database.
Uses AES-CBC with a key derived from NEXUS_SECRET environment variable.
Falls back to base64 obfuscation if cryptography library is not installed.
"""

import os
import base64
import hashlib

_SECRET: str | None = None


def _get_secret() -> str:
    """Get or generate the encryption secret."""
    global _SECRET
    if _SECRET:
        return _SECRET

    env_secret = os.environ.get("NEXUS_SECRET")
    if env_secret:
        _SECRET = env_secret
        return _SECRET

    # Auto-generate and persist to server data dir
    secret_path = os.path.join(os.path.dirname(__file__), "data", ".secret")
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            _SECRET = f.read().strip()
    else:
        _SECRET = base64.urlsafe_b64encode(os.urandom(32)).decode()
        os.makedirs(os.path.dirname(secret_path), exist_ok=True)
        with open(secret_path, "w") as f:
            f.write(_SECRET)

    return _SECRET


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte key from the secret using SHA-256."""
    return hashlib.sha256(secret.encode()).digest()


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""

    secret = _get_secret()
    key = _derive_key(secret)

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(plaintext.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        enc = cipher.encryptor()
        ct = enc.update(padded) + enc.finalize()
        return base64.urlsafe_b64encode(iv + ct).decode()
    except ImportError:
        # Fallback: XOR cipher with SHA-256 key stream
        data = plaintext.encode()
        encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return "xor:" + base64.urlsafe_b64encode(encrypted).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext string."""
    if not ciphertext:
        return ""

    secret = _get_secret()
    key = _derive_key(secret)

    if ciphertext.startswith("xor:"):
        # Fallback decryption
        raw = base64.urlsafe_b64decode(ciphertext[4:])
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
        return decrypted.decode()

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        raw = base64.urlsafe_b64decode(ciphertext)
        iv = raw[:16]
        ct = raw[16:]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        dec = cipher.decryptor()
        padded = dec.update(ct) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return (unpadder.update(padded) + unpadder.finalize()).decode()
    except ImportError:
        return ciphertext
    except Exception:
        # If decryption fails, return as-is (might be legacy plaintext)
        return ciphertext
