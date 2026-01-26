"""
S3 storage service for report files.

Handles uploading generated reports to S3 and generating presigned URLs
for downloads.
"""

import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import boto3
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not installed - S3 storage unavailable")


class StorageError(Exception):
    """Exception raised when storage operations fail."""
    pass


class ReportStorage:
    """
    S3 storage service for report files.

    Handles:
    - Uploading report files with organized path structure
    - Generating presigned download URLs
    - Deleting files
    - Archiving old reports
    """

    # Default configuration
    DEFAULT_BUCKET = "frontiermind-reports"
    DEFAULT_REGION = "us-east-1"
    DEFAULT_PRESIGNED_EXPIRY = 300  # 5 minutes

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region: Optional[str] = None,
        presigned_expiry: Optional[int] = None
    ):
        """
        Initialize the storage service.

        Args:
            bucket_name: S3 bucket name (defaults to REPORTS_S3_BUCKET env var)
            region: AWS region (defaults to AWS_REGION env var)
            presigned_expiry: Presigned URL expiry in seconds
        """
        if not BOTO3_AVAILABLE:
            raise ImportError(
                "boto3 is required for S3 storage. "
                "Install with: pip install boto3"
            )

        self._bucket = bucket_name or os.getenv(
            'REPORTS_S3_BUCKET', self.DEFAULT_BUCKET
        )
        self._region = region or os.getenv(
            'AWS_REGION', self.DEFAULT_REGION
        )
        self._presigned_expiry = presigned_expiry or int(os.getenv(
            'REPORTS_PRESIGNED_URL_EXPIRY', str(self.DEFAULT_PRESIGNED_EXPIRY)
        ))

        # Initialize S3 client lazily
        self._s3_client = None

    @property
    def s3_client(self):
        """Lazy-initialize S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client(
                's3',
                region_name=self._region
            )
        return self._s3_client

    def upload(
        self,
        content: bytes,
        org_id: int,
        filename: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload report content to S3.

        Args:
            content: File content as bytes
            org_id: Organization ID (for path organization)
            filename: Name of the file
            content_type: MIME type (optional)

        Returns:
            Full S3 path (key) of the uploaded file

        Raises:
            StorageError: If upload fails
        """
        # Build path: reports/{org_id}/{year}/{month}/{filename}
        now = datetime.utcnow()
        s3_key = f"reports/{org_id}/{now.year}/{now.month:02d}/{filename}"

        logger.info(f"Uploading to S3: bucket={self._bucket}, key={s3_key}")

        try:
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type

            self.s3_client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=content,
                **extra_args
            )

            logger.info(f"Upload successful: {s3_key} ({len(content)} bytes)")
            return s3_key

        except NoCredentialsError:
            raise StorageError(
                "AWS credentials not configured. "
                "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
            )
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            raise StorageError(
                f"S3 upload failed: {error_code} - {e}"
            )
        except Exception as e:
            raise StorageError(f"Upload failed: {e}")

    def get_presigned_url(
        self,
        file_path: str,
        expiry: Optional[int] = None,
        filename_override: Optional[str] = None
    ) -> str:
        """
        Generate a presigned URL for downloading a file.

        Args:
            file_path: S3 key/path of the file
            expiry: URL expiry in seconds (defaults to configured value)
            filename_override: Override the download filename

        Returns:
            Presigned URL string

        Raises:
            StorageError: If URL generation fails
        """
        expiry = expiry or self._presigned_expiry

        logger.debug(f"Generating presigned URL: key={file_path}, expiry={expiry}s")

        try:
            params = {
                'Bucket': self._bucket,
                'Key': file_path,
            }

            # Add content-disposition for filename override
            if filename_override:
                params['ResponseContentDisposition'] = (
                    f'attachment; filename="{filename_override}"'
                )

            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expiry
            )

            return url

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            raise StorageError(
                f"Failed to generate presigned URL: {error_code} - {e}"
            )
        except Exception as e:
            raise StorageError(f"Presigned URL generation failed: {e}")

    def delete(self, file_path: str) -> bool:
        """
        Delete a file from S3.

        Args:
            file_path: S3 key/path of the file

        Returns:
            True if deleted successfully

        Raises:
            StorageError: If deletion fails
        """
        logger.info(f"Deleting from S3: key={file_path}")

        try:
            self.s3_client.delete_object(
                Bucket=self._bucket,
                Key=file_path
            )
            return True

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            raise StorageError(
                f"S3 deletion failed: {error_code} - {e}"
            )
        except Exception as e:
            raise StorageError(f"Deletion failed: {e}")

    def exists(self, file_path: str) -> bool:
        """
        Check if a file exists in S3.

        Args:
            file_path: S3 key/path of the file

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self._bucket,
                Key=file_path
            )
            return True
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == '404':
                return False
            raise StorageError(f"Existence check failed: {e}")

    def get_file_info(self, file_path: str) -> dict:
        """
        Get metadata about a file in S3.

        Args:
            file_path: S3 key/path of the file

        Returns:
            Dictionary with file metadata (size, content_type, last_modified)

        Raises:
            StorageError: If file not found or operation fails
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self._bucket,
                Key=file_path
            )

            return {
                'size': response.get('ContentLength'),
                'content_type': response.get('ContentType'),
                'last_modified': response.get('LastModified'),
                'etag': response.get('ETag', '').strip('"'),
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404':
                raise StorageError(f"File not found: {file_path}")
            raise StorageError(f"Failed to get file info: {error_code} - {e}")

    def copy_to_archive(self, file_path: str) -> str:
        """
        Copy a file to the archive path (for Glacier transition).

        Args:
            file_path: S3 key/path of the file

        Returns:
            Archive path

        Raises:
            StorageError: If copy fails
        """
        # Build archive path: archive/{org_id}/{year}/{filename}
        parts = file_path.split('/')
        if len(parts) >= 4:
            org_id = parts[1]
            year = parts[2]
            filename = parts[-1]
            archive_key = f"archive/{org_id}/{year}/{filename}"
        else:
            archive_key = f"archive/{file_path}"

        logger.info(f"Archiving: {file_path} -> {archive_key}")

        try:
            self.s3_client.copy_object(
                Bucket=self._bucket,
                CopySource={'Bucket': self._bucket, 'Key': file_path},
                Key=archive_key,
                StorageClass='GLACIER'
            )

            return archive_key

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            raise StorageError(f"Archive copy failed: {error_code} - {e}")

    def list_reports(
        self,
        org_id: int,
        year: Optional[int] = None,
        month: Optional[int] = None,
        limit: int = 100
    ) -> list:
        """
        List report files for an organization.

        Args:
            org_id: Organization ID
            year: Optional year filter
            month: Optional month filter
            limit: Maximum files to return

        Returns:
            List of file info dictionaries
        """
        # Build prefix
        prefix = f"reports/{org_id}/"
        if year:
            prefix += f"{year}/"
            if month:
                prefix += f"{month:02d}/"

        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self._bucket,
                Prefix=prefix,
                MaxKeys=limit
            )

            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'],
                })

            return files

        except ClientError as e:
            raise StorageError(f"List operation failed: {e}")


class LocalStorage:
    """
    Local filesystem storage for development/testing.

    Drop-in replacement for ReportStorage when S3 is not available.
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize local storage.

        Args:
            base_path: Base directory for storing files
        """
        self._base_path = base_path or os.getenv(
            'REPORTS_LOCAL_PATH',
            '/tmp/frontiermind-reports'
        )
        os.makedirs(self._base_path, exist_ok=True)

    def upload(
        self,
        content: bytes,
        org_id: int,
        filename: str,
        content_type: Optional[str] = None
    ) -> str:
        """Upload file to local filesystem."""
        import pathlib

        now = datetime.utcnow()
        rel_path = f"reports/{org_id}/{now.year}/{now.month:02d}"
        full_dir = pathlib.Path(self._base_path) / rel_path
        full_dir.mkdir(parents=True, exist_ok=True)

        file_path = full_dir / filename
        file_path.write_bytes(content)

        return f"{rel_path}/{filename}"

    def get_presigned_url(
        self,
        file_path: str,
        expiry: Optional[int] = None,
        filename_override: Optional[str] = None
    ) -> str:
        """Return file:// URL for local files."""
        import pathlib
        full_path = pathlib.Path(self._base_path) / file_path
        return f"file://{full_path}"

    def delete(self, file_path: str) -> bool:
        """Delete local file."""
        import pathlib
        full_path = pathlib.Path(self._base_path) / file_path
        if full_path.exists():
            full_path.unlink()
            return True
        return False

    def exists(self, file_path: str) -> bool:
        """Check if local file exists."""
        import pathlib
        full_path = pathlib.Path(self._base_path) / file_path
        return full_path.exists()


def get_storage() -> ReportStorage:
    """
    Factory function to get the appropriate storage backend.

    Returns ReportStorage for S3, or LocalStorage if S3 is not configured.
    """
    # Check if S3 is configured
    if os.getenv('REPORTS_S3_BUCKET') or os.getenv('AWS_ACCESS_KEY_ID'):
        try:
            return ReportStorage()
        except ImportError:
            logger.warning("boto3 not available, falling back to local storage")

    # Fall back to local storage
    logger.info("Using local storage for reports")
    return LocalStorage()
