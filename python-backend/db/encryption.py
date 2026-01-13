"""
Encryption utilities for PII mapping data.

Provides AES-256-GCM encryption for PII mappings before storage in database.
Uses the Cryptography library for secure encryption/decryption.
"""

import os
import json
import logging
from typing import Dict, Any
from base64 import b64encode, b64decode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

# Encryption method identifier (stored in database)
ENCRYPTION_METHOD = "aes-256-gcm"


def _get_encryption_key() -> bytes:
    """
    Get the encryption key from environment variable.

    Returns:
        32-byte encryption key for AES-256

    Raises:
        ValueError: If ENCRYPTION_KEY not set or invalid length
    """
    key_b64 = os.getenv("ENCRYPTION_KEY")
    if not key_b64:
        raise ValueError(
            "ENCRYPTION_KEY not found in environment. "
            "Generate with: python -c 'import os; import base64; "
            "print(base64.b64encode(os.urandom(32)).decode())'"
        )

    try:
        key = b64decode(key_b64)
        if len(key) != 32:
            raise ValueError(f"Encryption key must be 32 bytes, got {len(key)}")
        return key
    except Exception as e:
        raise ValueError(f"Invalid ENCRYPTION_KEY format: {e}")


def encrypt_pii_mapping(pii_mapping: Dict[str, Any]) -> bytes:
    """
    Encrypt PII mapping dictionary for secure storage.

    Uses AES-256-GCM authenticated encryption with a random nonce.
    The nonce is prepended to the ciphertext for later decryption.

    Args:
        pii_mapping: Dictionary containing PII mappings
            Example: {
                "John Doe": "<PERSON_1>",
                "john@example.com": "<EMAIL_1>",
                "original_text": "Full contract text with PII",
                "anonymized_text": "Full contract text with <PERSON_1>"
            }

    Returns:
        Encrypted bytes (nonce + ciphertext + auth_tag)

    Raises:
        ValueError: If ENCRYPTION_KEY not set
        Exception: If encryption fails
    """
    try:
        # Get encryption key
        key = _get_encryption_key()

        # Convert mapping to JSON bytes
        plaintext = json.dumps(pii_mapping, ensure_ascii=False).encode('utf-8')

        # Generate random nonce (12 bytes for GCM)
        nonce = os.urandom(12)

        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        # Return nonce + ciphertext (ciphertext already includes auth tag)
        encrypted_data = nonce + ciphertext

        logger.debug(f"Encrypted PII mapping: {len(plaintext)} bytes -> {len(encrypted_data)} bytes")
        return encrypted_data

    except Exception as e:
        logger.error(f"PII encryption failed: {e}")
        raise


def decrypt_pii_mapping(encrypted_data: bytes) -> Dict[str, Any]:
    """
    Decrypt PII mapping from encrypted bytes.

    Args:
        encrypted_data: Encrypted bytes from database (nonce + ciphertext + auth_tag)

    Returns:
        Decrypted PII mapping dictionary

    Raises:
        ValueError: If ENCRYPTION_KEY not set or data invalid
        InvalidTag: If authentication tag verification fails (tampering detected)
        Exception: If decryption fails
    """
    try:
        # Get encryption key
        key = _get_encryption_key()

        # Extract nonce and ciphertext
        if len(encrypted_data) < 12:
            raise ValueError("Encrypted data too short (missing nonce)")

        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]

        # Decrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        # Parse JSON
        pii_mapping = json.loads(plaintext.decode('utf-8'))

        logger.debug(f"Decrypted PII mapping: {len(encrypted_data)} bytes -> {len(plaintext)} bytes")
        return pii_mapping

    except InvalidTag as e:
        logger.error("PII decryption failed: Authentication tag verification failed (data may be tampered)")
        raise ValueError("Decryption failed: Data integrity check failed")
    except Exception as e:
        logger.error(f"PII decryption failed: {e}")
        raise


def generate_encryption_key() -> str:
    """
    Generate a new random encryption key for AES-256.

    Returns:
        Base64-encoded 32-byte key

    Usage:
        key = generate_encryption_key()
        print(f"Add to .env file:\nENCRYPTION_KEY={key}")
    """
    key = os.urandom(32)
    key_b64 = b64encode(key).decode('ascii')
    return key_b64


if __name__ == "__main__":
    # Generate encryption key for setup
    print("=" * 80)
    print("PII Encryption Key Generator")
    print("=" * 80)
    print("\nGenerated encryption key (add to .env file):\n")
    key = generate_encryption_key()
    print(f"ENCRYPTION_KEY={key}")
    print("\n" + "=" * 80)
    print("Keep this key secure! Loss of this key means loss of PII data.")
    print("=" * 80)
