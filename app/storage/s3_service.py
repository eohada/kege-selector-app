"""
S3/MinIO storage service for BooStudy.
Wraps boto3 to provide file upload, download, and URL generation.
Falls back to local filesystem if S3 is not configured.
"""
import os
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, app=None):
        self.client = None
        self.bucket = None
        self.use_s3 = False
        self.local_upload_dir = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.bucket = app.config.get('S3_BUCKET', 'boostudy')
        self.local_upload_dir = app.config.get(
            'UPLOAD_FOLDER',
            os.path.join(app.root_path, '..', 'uploads'),
        )

        endpoint = app.config.get('S3_ENDPOINT_URL')
        access_key = app.config.get('S3_ACCESS_KEY')
        secret_key = app.config.get('S3_SECRET_KEY')

        if endpoint and access_key and secret_key:
            import boto3
            self.client = boto3.client(
                's3',
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            self.use_s3 = True
            self._ensure_bucket()
            logger.info(f"S3 storage initialized: {endpoint}/{self.bucket}")
        else:
            os.makedirs(self.local_upload_dir, exist_ok=True)
            logger.info(f"Using local storage: {self.local_upload_dir}")

    def _ensure_bucket(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception as e:
                logger.error(f"Failed to create bucket: {e}")

    def upload_file(self, file_obj, folder='uploads', filename=None):
        """Upload a file and return the storage key/path."""
        if not filename:
            original = secure_filename(file_obj.filename or 'file')
            ext = os.path.splitext(original)[1]
            filename = f"{uuid.uuid4().hex[:12]}{ext}"

        key = f"{folder}/{datetime.utcnow().strftime('%Y/%m')}/{filename}"

        if self.use_s3:
            self.client.upload_fileobj(file_obj, self.bucket, key)
            return f"s3://{self.bucket}/{key}"
        else:
            path = os.path.join(self.local_upload_dir, key.replace('/', os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            file_obj.save(path)
            return key

    def get_url(self, key, expires_in=3600):
        """Get a URL for a stored file."""
        if not key:
            return None
        if self.use_s3 and key.startswith('s3://'):
            s3_key = key.split('/', 3)[-1]
            return self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': s3_key},
                ExpiresIn=expires_in,
            )
        else:
            from flask import url_for
            return url_for('static', filename=f'../{key}')

    def delete_file(self, key):
        """Delete a file from storage."""
        if not key:
            return
        if self.use_s3 and key.startswith('s3://'):
            s3_key = key.split('/', 3)[-1]
            self.client.delete_object(Bucket=self.bucket, Key=s3_key)
        else:
            path = os.path.join(self.local_upload_dir, key.replace('/', os.sep))
            if os.path.exists(path):
                os.remove(path)


storage = StorageService()
