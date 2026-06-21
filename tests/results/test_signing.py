"""Test the detached-signature crypto boundary (signing.py).

These are the pure helpers behind real tamper-evidence: an Ed25519 detached
signature over an artifact's content_hash. Only a holder of the private key can
produce a signature that the matching public key accepts — which is what makes a
forged-but-recomputed artifact detectable (F-C2).
"""

from copeca.results.signing import (
    generate_keypair,
    load_private_key_pem,
    load_public_key_pem,
    serialize_private_key_pem,
    serialize_public_key_pem,
    sign,
    verify_signature,
)


class TestSignVerifyRoundTrip:
    def test_signature_from_private_key_verifies_with_matching_public_key(self):
        """A signature produced by a private key verifies under its public key."""
        private_key, public_key = generate_keypair()
        content_hash = "a" * 64

        signature = sign(content_hash, private_key)

        assert isinstance(signature, bytes)
        assert verify_signature(content_hash, signature, public_key) is True

    def test_signature_over_different_hash_does_not_verify(self):
        """A signature is bound to the exact content_hash it was made over."""
        private_key, public_key = generate_keypair()
        signature = sign("a" * 64, private_key)

        # Verifying against a different content_hash must fail.
        assert verify_signature("b" * 64, signature, public_key) is False

    def test_signature_does_not_verify_under_wrong_public_key(self):
        """A different keypair's public key must reject the signature."""
        private_key, _public_key = generate_keypair()
        _other_private, other_public = generate_keypair()
        content_hash = "c" * 64

        signature = sign(content_hash, private_key)

        assert verify_signature(content_hash, signature, other_public) is False

    def test_corrupted_signature_does_not_verify(self):
        """Flipping a byte of the signature must make verification fail, not raise."""
        private_key, public_key = generate_keypair()
        content_hash = "d" * 64
        signature = bytearray(sign(content_hash, private_key))

        signature[0] ^= 0xFF

        assert verify_signature(content_hash, bytes(signature), public_key) is False

    def test_verify_signature_is_total_on_garbage_bytes(self):
        """verify_signature returns False (never raises) on non-signature bytes."""
        _private_key, public_key = generate_keypair()

        assert verify_signature("e" * 64, b"not a real signature", public_key) is False


class TestPemRoundTrip:
    def test_private_key_pem_round_trip(self):
        """A private key survives serialize -> load and still signs verifiably."""
        private_key, public_key = generate_keypair()

        pem = serialize_private_key_pem(private_key)
        assert b"PRIVATE KEY" in pem
        reloaded = load_private_key_pem(pem)

        signature = sign("f" * 64, reloaded)
        assert verify_signature("f" * 64, signature, public_key) is True

    def test_public_key_pem_round_trip(self):
        """A public key survives serialize -> load and still verifies."""
        private_key, public_key = generate_keypair()

        pem = serialize_public_key_pem(public_key)
        assert b"PUBLIC KEY" in pem
        reloaded = load_public_key_pem(pem)

        signature = sign("0" * 64, private_key)
        assert verify_signature("0" * 64, signature, reloaded) is True
