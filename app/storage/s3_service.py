"""
S3/MinIO storage service for BooStudy.
Wraps boto3 to provide file upload, download, and URL generation.
Falls back to local filesystem if S3 is not configured.
"""
import os
import uuid
import logging
import io
import json
import mimetypes
from datetime import datetime
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, app=None):
        self.client = None
        self.bucket = None
        self.use_s3 = False
        self.use_google_drive = False
        self.google_drive = None
        self.google_drive_folder_id = None
        self.local_upload_dir = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.bucket = app.config.get('S3_BUCKET', 'boostudy')
        self.local_upload_dir = app.config.get(
            'UPLOAD_FOLDER',
            os.path.join(app.root_path, '..', 'uploads'),
        )
        storage_backend = (app.config.get('STORAGE_BACKEND') or '').strip().lower()

        if storage_backend == 'google_drive':
            credentials_info = app.config.get('GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON')
            credentials_file = app.config.get('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE')
            oauth_client_info = app.config.get('GOOGLE_DRIVE_OAUTH_CLIENT_JSON')
            oauth_client_file = app.config.get('GOOGLE_DRIVE_OAUTH_CLIENT_FILE')
            oauth_refresh_token = app.config.get('GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN')
            self.google_drive_folder_id = app.config.get('GOOGLE_DRIVE_FOLDER_ID')
            if not credentials_info and credentials_file and os.path.isfile(credentials_file):
                with open(credentials_file, 'r', encoding='utf-8') as credentials_stream:
                    credentials_info = credentials_stream.read()
            if not oauth_client_info and oauth_client_file and os.path.isfile(oauth_client_file):
                with open(oauth_client_file, 'r', encoding='utf-8') as oauth_stream:
                    oauth_client_info = oauth_stream.read()
            if (not credentials_info and not (oauth_client_info and oauth_refresh_token)) or not self.google_drive_folder_id:
                raise RuntimeError(
                    'Google Drive storage requires a folder ID and either an OAuth refresh token for My Drive '
                    'or service-account credentials for a shared drive.'
                )
            try:
                from google.oauth2 import service_account, credentials as oauth_credentials
                from googleapiclient.discovery import build

                drive_scope = ['https://www.googleapis.com/auth/drive']
                if oauth_client_info and oauth_refresh_token:
                    client_info = json.loads(oauth_client_info)
                    client_info = client_info.get('installed') or client_info.get('web') or client_info
                    credentials = oauth_credentials.Credentials(
                        token=None,
                        refresh_token=oauth_refresh_token,
                        token_uri=client_info.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=client_info['client_id'],
                        client_secret=client_info['client_secret'],
                        scopes=drive_scope,
                    )
                else:
                    credentials = service_account.Credentials.from_service_account_info(
                        json.loads(credentials_info),
                        scopes=drive_scope,
                    )
                self.google_drive = build('drive', 'v3', credentials=credentials, cache_discovery=False)
            except Exception as exc:
                raise RuntimeError('Google Drive storage could not be initialized.') from exc
            self.use_google_drive = True
            logger.info('Google Drive storage initialized for folder %s', self.google_drive_folder_id)
            return

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

        if self.use_google_drive:
            from googleapiclient.http import MediaIoBaseUpload

            upload_stream = getattr(file_obj, 'stream', file_obj)
            if hasattr(upload_stream, 'seek'):
                upload_stream.seek(0)
            original_name = secure_filename(getattr(file_obj, 'filename', '') or filename)
            display_name = f"{folder}_{datetime.utcnow().strftime('%Y%m')}_{original_name}"
            mime_type = getattr(file_obj, 'mimetype', None) or mimetypes.guess_type(original_name)[0] or 'application/octet-stream'
            metadata = {
                'name': display_name,
                'parents': [self.google_drive_folder_id],
                'description': f'BooStudy asset key: {key}',
            }
            created = self.google_drive.files().create(
                body=metadata,
                media_body=MediaIoBaseUpload(upload_stream, mimetype=mime_type, resumable=True),
                fields='id',
                supportsAllDrives=True,
            ).execute()
            return f"gdrive://{created['id']}"

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
        if self.use_google_drive and key.startswith('gdrive://'):
            from flask import url_for
            file_id = key.removeprefix('gdrive://')
            return url_for('storage.serve_google_drive_file', file_id=file_id)
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
        if self.use_google_drive and key.startswith('gdrive://'):
            file_id = key.removeprefix('gdrive://')
            self.google_drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return
        if self.use_s3 and key.startswith('s3://'):
            s3_key = key.split('/', 3)[-1]
            self.client.delete_object(Bucket=self.bucket, Key=s3_key)
        else:
            path = os.path.join(self.local_upload_dir, key.replace('/', os.sep))
            if os.path.exists(path):
                os.remove(path)

    def download_google_drive_file(self, file_id):
        """Return bytes and MIME type for a private Drive file."""
        if not self.use_google_drive or not self.google_drive:
            raise RuntimeError('Google Drive storage is not configured.')
        metadata = self.google_drive.files().get(
            fileId=file_id,
            fields='mimeType,name',
            supportsAllDrives=True,
        ).execute()
        contents = self.google_drive.files().get_media(
            fileId=file_id,
            supportsAllDrives=True,
        ).execute()
        return io.BytesIO(contents), metadata.get('mimeType') or 'application/octet-stream', metadata.get('name') or 'file'


storage = StorageService()
