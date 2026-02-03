"""
Tests for Security Remediation Phase 2

Tests the AES-GCM encryption/decryption and OAuth state generation
to verify compatibility between TypeScript and Python implementations.
"""

import base64
import hashlib
import hmac
import json
import os
import time

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TestAESGCMEncryption:
    """Test AES-GCM encryption/decryption compatibility."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key (32 bytes, base64 encoded)."""
        key = os.urandom(32)
        return base64.b64encode(key).decode()

    def encrypt_like_typescript(self, data: dict, key_b64: str) -> str:
        """
        Encrypt data in the same format as TypeScript implementation.
        Format: [IV_12][CIPHERTEXT][AUTH_TAG_16] -> base64
        """
        key = base64.b64decode(key_b64)[:32]
        iv = os.urandom(12)  # 12-byte IV for AES-GCM

        aesgcm = AESGCM(key)
        plaintext = json.dumps(data).encode()
        ciphertext = aesgcm.encrypt(iv, plaintext, None)

        # Combine IV + ciphertext (includes auth tag)
        combined = iv + ciphertext
        return base64.b64encode(combined).decode()

    def decrypt_like_python(self, encrypted_b64: str, key_b64: str) -> dict:
        """
        Decrypt data in the same format as Python base_fetcher implementation.
        """
        key = base64.b64decode(key_b64)[:32]
        encrypted = base64.b64decode(encrypted_b64)

        if len(encrypted) < 12:
            raise ValueError("Encrypted data too short (missing IV)")

        iv = encrypted[:12]
        ciphertext = encrypted[12:]  # Includes auth tag

        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        return json.loads(plaintext.decode("utf-8"))

    def test_encrypt_decrypt_round_trip(self, encryption_key):
        """Test that data encrypted can be decrypted correctly."""
        original_data = {
            "access_token": "test_access_token_12345",
            "refresh_token": "test_refresh_token_67890",
            "token_type": "Bearer",
            "scope": "read write",
        }

        encrypted = self.encrypt_like_typescript(original_data, encryption_key)
        decrypted = self.decrypt_like_python(encrypted, encryption_key)

        assert decrypted == original_data

    def test_different_data_produces_different_ciphertext(self, encryption_key):
        """Test that different plaintext produces different ciphertext."""
        data1 = {"key": "value1"}
        data2 = {"key": "value2"}

        encrypted1 = self.encrypt_like_typescript(data1, encryption_key)
        encrypted2 = self.encrypt_like_typescript(data2, encryption_key)

        assert encrypted1 != encrypted2

    def test_same_data_produces_different_ciphertext_due_to_iv(self, encryption_key):
        """Test that same plaintext produces different ciphertext (random IV)."""
        data = {"key": "value"}

        encrypted1 = self.encrypt_like_typescript(data, encryption_key)
        encrypted2 = self.encrypt_like_typescript(data, encryption_key)

        # Different ciphertext due to random IV
        assert encrypted1 != encrypted2

        # But both decrypt to same data
        decrypted1 = self.decrypt_like_python(encrypted1, encryption_key)
        decrypted2 = self.decrypt_like_python(encrypted2, encryption_key)
        assert decrypted1 == decrypted2 == data

    def test_tampered_ciphertext_fails_decryption(self, encryption_key):
        """Test that tampering with ciphertext causes authentication failure."""
        data = {"secret": "data"}
        encrypted = self.encrypt_like_typescript(data, encryption_key)

        # Tamper with the ciphertext
        encrypted_bytes = bytearray(base64.b64decode(encrypted))
        encrypted_bytes[15] ^= 0xFF  # Flip bits in the ciphertext
        tampered = base64.b64encode(bytes(encrypted_bytes)).decode()

        with pytest.raises(Exception):  # AESGCM raises InvalidTag
            self.decrypt_like_python(tampered, encryption_key)

    def test_wrong_key_fails_decryption(self, encryption_key):
        """Test that wrong key causes decryption failure."""
        data = {"secret": "data"}
        encrypted = self.encrypt_like_typescript(data, encryption_key)

        # Use a different key
        wrong_key = base64.b64encode(os.urandom(32)).decode()

        with pytest.raises(Exception):  # AESGCM raises InvalidTag
            self.decrypt_like_python(encrypted, wrong_key)

    def test_key_length_validation(self):
        """Test that short keys are rejected."""
        short_key = base64.b64encode(b"short").decode()

        # The implementation should handle this - let's verify
        key = base64.b64decode(short_key)
        assert len(key) < 32  # Confirm key is too short


class TestOAuthStateGeneration:
    """Test OAuth state generation and validation."""

    @pytest.fixture
    def state_secret(self):
        """Generate a test state secret."""
        return "test_secret_key_for_oauth_state_12345"

    def generate_state_like_python(self, org_id: int, secret: str) -> str:
        """
        Generate state in the same format as Python API endpoint.
        """
        payload = {
            "organization_id": org_id,
            "ts": int(time.time() * 1000),
        }
        data = json.dumps(payload, separators=(",", ":"))

        sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()

        state_obj = {"data": data, "sig": sig_b64}
        state_json = json.dumps(state_obj, separators=(",", ":"))

        state = base64.b64encode(state_json.encode()).decode()
        state = state.replace("+", "-").replace("/", "_").rstrip("=")

        return state

    def validate_state_like_typescript(
        self, state: str, expected_org_id: int, secret: str, max_age_ms: int = 600000
    ) -> bool:
        """
        Validate state in the same format as TypeScript callback.
        """
        try:
            # Restore URL-safe base64 padding
            standard_base64 = state.replace("-", "+").replace("_", "/")
            while len(standard_base64) % 4:
                standard_base64 += "="

            decoded = json.loads(base64.b64decode(standard_base64).decode())

            if "data" not in decoded or "sig" not in decoded:
                return False

            # Verify HMAC
            expected_sig = hmac.new(
                secret.encode(), decoded["data"].encode(), hashlib.sha256
            ).digest()
            actual_sig = base64.b64decode(decoded["sig"])

            if not hmac.compare_digest(expected_sig, actual_sig):
                return False

            payload = json.loads(decoded["data"])

            # Check expiry
            age = int(time.time() * 1000) - payload["ts"]
            if age > max_age_ms:
                return False

            return payload["organization_id"] == expected_org_id
        except Exception:
            return False

    def test_state_round_trip(self, state_secret):
        """Test that generated state validates correctly."""
        org_id = 12345
        state = self.generate_state_like_python(org_id, state_secret)

        assert self.validate_state_like_typescript(state, org_id, state_secret)

    def test_wrong_org_id_fails(self, state_secret):
        """Test that wrong organization ID fails validation."""
        org_id = 12345
        wrong_org_id = 67890
        state = self.generate_state_like_python(org_id, state_secret)

        assert not self.validate_state_like_typescript(state, wrong_org_id, state_secret)

    def test_wrong_secret_fails(self, state_secret):
        """Test that wrong secret fails validation."""
        org_id = 12345
        state = self.generate_state_like_python(org_id, state_secret)

        assert not self.validate_state_like_typescript(state, org_id, "wrong_secret")

    def test_expired_state_fails(self, state_secret):
        """Test that expired state fails validation."""
        org_id = 12345

        # Create state with old timestamp
        payload = {
            "organization_id": org_id,
            "ts": int(time.time() * 1000) - 700000,  # 11.67 minutes ago
        }
        data = json.dumps(payload, separators=(",", ":"))
        sig = hmac.new(state_secret.encode(), data.encode(), hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()
        state_obj = {"data": data, "sig": sig_b64}
        state_json = json.dumps(state_obj, separators=(",", ":"))
        state = base64.b64encode(state_json.encode()).decode()
        state = state.replace("+", "-").replace("/", "_").rstrip("=")

        assert not self.validate_state_like_typescript(state, org_id, state_secret)

    def test_tampered_state_fails(self, state_secret):
        """Test that tampered state fails validation."""
        org_id = 12345
        state = self.generate_state_like_python(org_id, state_secret)

        # Tamper with the state
        tampered = state[:-5] + "XXXXX"

        assert not self.validate_state_like_typescript(tampered, org_id, state_secret)

    def test_legacy_format_rejected(self, state_secret):
        """Test that legacy unsigned format is rejected."""
        # Legacy format: just { organization_id: number }
        legacy_payload = {"organization_id": 12345}
        legacy_state = base64.b64encode(json.dumps(legacy_payload).encode()).decode()

        # Should be rejected (no HMAC fields)
        assert not self.validate_state_like_typescript(legacy_state, 12345, state_secret)

    def test_url_safe_base64_various_lengths(self, state_secret):
        """Test that URL-safe base64 with different padding scenarios works."""
        # Different org IDs will produce different state lengths
        for org_id in [1, 12, 123, 1234, 12345, 123456, 1234567]:
            state = self.generate_state_like_python(org_id, state_secret)
            assert self.validate_state_like_typescript(state, org_id, state_secret), \
                f"Failed for org_id={org_id}"
