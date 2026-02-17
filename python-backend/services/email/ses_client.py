"""
AWS SES email sending client.

Wraps boto3 SES client with configuration from environment variables.
"""

import logging
import os
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class SESError(Exception):
    """Raised when SES operations fail."""
    pass


class SESClient:
    """
    AWS Simple Email Service client.

    Configuration via environment variables:
    - SES_SENDER_EMAIL: Verified sender email address
    - SES_SENDER_NAME: Display name for sender
    - SES_CONFIGURATION_SET: Optional SES configuration set for tracking
    - AWS_REGION: AWS region (default: us-east-1)
    """

    def __init__(self):
        self.sender_email = os.getenv("SES_SENDER_EMAIL", "")
        self.sender_name = os.getenv("SES_SENDER_NAME", "FrontierMind")
        self.configuration_set = os.getenv("SES_CONFIGURATION_SET")
        region = os.getenv("AWS_REGION", "us-east-1")

        self._client = boto3.client("ses", region_name=region)
        logger.info(f"SES client initialized: sender={self.sender_email}, region={region}")

    @property
    def sender(self) -> str:
        """Formatted sender address."""
        if self.sender_name:
            return f"{self.sender_name} <{self.sender_email}>"
        return self.sender_email

    def send_email(
        self,
        to: list[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        reply_to: Optional[list[str]] = None,
    ) -> str:
        """
        Send an email via SES.

        Args:
            to: List of recipient email addresses
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body (fallback)
            reply_to: Optional reply-to addresses

        Returns:
            SES message ID

        Raises:
            SESError: If sending fails
        """
        if not self.sender_email:
            raise SESError("SES_SENDER_EMAIL not configured")

        body: Dict[str, Any] = {
            "Html": {"Charset": "UTF-8", "Data": html_body},
        }
        if text_body:
            body["Text"] = {"Charset": "UTF-8", "Data": text_body}

        kwargs: Dict[str, Any] = {
            "Source": self.sender,
            "Destination": {"ToAddresses": to},
            "Message": {
                "Subject": {"Charset": "UTF-8", "Data": subject},
                "Body": body,
            },
        }

        if reply_to:
            kwargs["ReplyToAddresses"] = reply_to

        if self.configuration_set:
            kwargs["ConfigurationSetName"] = self.configuration_set

        try:
            response = self._client.send_email(**kwargs)
            message_id = response["MessageId"]
            logger.info(f"Email sent: message_id={message_id}, to={to}, subject={subject[:50]}")
            return message_id

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            logger.error(f"SES send failed: {error_code} - {error_msg}")
            raise SESError(f"SES error ({error_code}): {error_msg}") from e

    def check_sending_quota(self) -> Dict[str, Any]:
        """
        Check SES sending quota and current usage.

        Returns:
            Dict with max_24h_send, sent_last_24h, max_send_rate
        """
        try:
            quota = self._client.get_send_quota()
            return {
                "max_24h_send": quota["Max24HourSend"],
                "sent_last_24h": quota["SentLast24Hours"],
                "max_send_rate": quota["MaxSendRate"],
            }
        except ClientError as e:
            logger.error(f"Failed to check SES quota: {e}")
            raise SESError(f"Failed to check quota: {e}") from e
