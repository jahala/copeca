"""Ed25519 detached signatures over an artifact's content_hash.

Architecture: pure crypto boundary. These helpers compute on values — a key
object in, bytes/bool out. No filesystem or network I/O lives here; PEM bytes
are read/written by callers (the CLI and artifact/verification adapters). This
keeps signing and verification deterministic, total, and trivially testable.

Why this exists (F-C2): the integrity manifest (a SHA-256 over per-file hashes,
stored inside the zip) detects accidental corruption but NOT deliberate
tampering — an attacker edits a file, recomputes the manifest, and it passes. A
detached signature over the content_hash that only a private-key holder can
produce closes that hole: a tampered-and-recomputed artifact fails signature
verification because the attacker cannot re-sign the new content_hash.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a fresh Ed25519 keypair.

    Returns:
        (private_key, public_key). The private key signs; the public key (safe to
        publish) verifies.
    """
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def sign(content_hash: str, private_key: Ed25519PrivateKey) -> bytes:
    """Produce a detached signature over ``content_hash``.

    Pure function — no I/O. The message signed is the UTF-8 encoding of the
    hex content_hash string, so the signature is bound to that exact value.

    Args:
        content_hash: The artifact's content_hash (hex SHA-256 string).
        private_key: The Ed25519 private key to sign with.

    Returns:
        The 64-byte raw Ed25519 signature.
    """
    return private_key.sign(content_hash.encode("utf-8"))


def verify_signature(content_hash: str, signature: bytes, public_key: Ed25519PublicKey) -> bool:
    """Verify a detached signature over ``content_hash``.

    Pure & total — returns False for any invalid or malformed signature rather
    than raising, so callers get a clean boolean contract.

    Args:
        content_hash: The content_hash the signature is claimed to cover.
        signature: The detached signature bytes.
        public_key: The trusted Ed25519 public key.

    Returns:
        True iff ``signature`` is a valid Ed25519 signature by ``public_key``
        over ``content_hash``; False otherwise.
    """
    try:
        public_key.verify(signature, content_hash.encode("utf-8"))
        return True
    except InvalidSignature:
        return False


def serialize_private_key_pem(private_key: Ed25519PrivateKey) -> bytes:
    """Serialize a private key to unencrypted PKCS#8 PEM bytes.

    Pure function — no I/O. Callers write the bytes to a file. The key is
    unencrypted: protect the file with filesystem permissions and keep it out of
    version control (operator responsibility — copeca never stores keys).
    """
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def serialize_public_key_pem(public_key: Ed25519PublicKey) -> bytes:
    """Serialize a public key to SubjectPublicKeyInfo PEM bytes (pure, no I/O)."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def load_private_key_pem(pem: bytes) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from unencrypted PEM bytes.

    Pure function — the caller reads the file. Raises if the PEM is not an
    unencrypted Ed25519 private key.

    Raises:
        ValueError: If the PEM does not decode to an Ed25519 private key.
    """
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"Expected an Ed25519 private key, got {type(key).__name__}")
    return key


def load_public_key_pem(pem: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM bytes.

    Pure function — the caller reads the file.

    Raises:
        ValueError: If the PEM does not decode to an Ed25519 public key.
    """
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"Expected an Ed25519 public key, got {type(key).__name__}")
    return key


def load_private_key_file(path: str) -> Ed25519PrivateKey:
    """Read a private key PEM file and load it (thin I/O wrapper for the CLI)."""
    from pathlib import Path

    return load_private_key_pem(Path(path).read_bytes())


def load_public_key_file(path: str) -> Ed25519PublicKey:
    """Read a public key PEM file and load it (thin I/O wrapper for the CLI)."""
    from pathlib import Path

    return load_public_key_pem(Path(path).read_bytes())
