"""
SNS Message Signature Verification.

Full certificate-based signature validation for AWS SNS webhook messages.
Validates SigningCertURL hostname, downloads and caches signing certificates,
builds canonical strings, and verifies RSA-SHA1 signatures.
"""

import base64
import logging
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, utils

logger = logging.getLogger(__name__)

# SNS notification types and their canonical field ordering
_NOTIFICATION_FIELDS = [
    "Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type",
]
_SUBSCRIPTION_FIELDS = [
    "Message", "MessageId", "SubscribeURL", "Timestamp", "TopicArn", "Type",
]


class SNSVerificationError(Exception):
    """Raised when SNS message verification fails."""
    pass


class SNSVerifier:
    """Verifies AWS SNS message signatures."""

    ALLOWED_TOPIC_ARNS = frozenset({
        "arn:aws:sns:us-east-1:724772070642:frontiermind-email-ingest",
    })

    def verify(self, message: dict) -> bool:
        """
        Verify an SNS message signature.

        Raises SNSVerificationError on failure. Returns True on success.
        """
        self._validate_cert_url(message["SigningCertURL"])
        self._validate_topic_arn(message["TopicArn"])

        cert_pem = _fetch_certificate(message["SigningCertURL"])
        canonical = self._build_canonical_string(message)
        signature = base64.b64decode(message["Signature"])

        self._verify_signature(cert_pem, canonical, signature)
        return True

    @staticmethod
    def _validate_cert_url(cert_url: str) -> None:
        """Ensure SigningCertURL is HTTPS on an SNS amazonaws.com host."""
        parsed = urlparse(cert_url)
        if parsed.scheme != "https":
            raise SNSVerificationError(f"SigningCertURL must be HTTPS: {cert_url}")
        if not parsed.hostname or not parsed.hostname.endswith(".amazonaws.com"):
            raise SNSVerificationError(
                f"SigningCertURL hostname must be *.amazonaws.com: {parsed.hostname}"
            )
        # Must match sns.<region>.amazonaws.com
        parts = parsed.hostname.split(".")
        if len(parts) < 3 or parts[0] != "sns":
            raise SNSVerificationError(
                f"SigningCertURL must be sns.<region>.amazonaws.com: {parsed.hostname}"
            )

    def _validate_topic_arn(self, topic_arn: str) -> None:
        if topic_arn not in self.ALLOWED_TOPIC_ARNS:
            raise SNSVerificationError(f"TopicArn not in allowlist: {topic_arn}")

    @staticmethod
    def _build_canonical_string(message: dict) -> bytes:
        """Build the canonical string that SNS signs."""
        msg_type = message.get("Type", "")

        if msg_type == "Notification":
            fields = _NOTIFICATION_FIELDS
        else:
            # SubscriptionConfirmation and UnsubscribeConfirmation
            fields = _SUBSCRIPTION_FIELDS

        parts = []
        for field in fields:
            value = message.get(field)
            if value is not None:
                parts.append(field)
                parts.append(value)

        return "\n".join(parts + [""]).encode("utf-8")

    @staticmethod
    def _verify_signature(cert_pem: bytes, canonical: bytes, signature: bytes) -> None:
        """Verify RSA-SHA1 signature using the signing certificate."""
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()

        try:
            public_key.verify(
                signature,
                canonical,
                padding.PKCS1v15(),
                hashes.SHA1(),
            )
        except Exception as e:
            raise SNSVerificationError(f"Signature verification failed: {e}") from e


@lru_cache(maxsize=16)
def _fetch_certificate(cert_url: str) -> bytes:
    """Download and cache an SNS signing certificate."""
    try:
        resp = httpx.get(cert_url, timeout=10.0)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise SNSVerificationError(f"Failed to fetch signing certificate: {e}") from e
