"""Authorize BooStudy's private Google Drive storage from a desktop browser.

The resulting file is a secret. Keep it outside the repository and transfer it
to the server over SSH when configuring the production environment.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive'
DEFAULT_OUTPUT = Path.home() / '.config' / 'boostudy' / 'google-drive-oauth.json'


def main() -> None:
    parser = argparse.ArgumentParser(description='Authorize BooStudy to use a folder in your Google Drive.')
    parser.add_argument('client_json', type=Path, help='Downloaded OAuth client JSON from Google Cloud.')
    parser.add_argument('--folder-id', default='1YkwyCAzWBDsozXvowVF-TZvbpJ0g_jON')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    client_info = json.loads(args.client_json.read_text(encoding='utf-8'))
    if not (client_info.get('installed') or client_info.get('web')):
        parser.error('The JSON file is not a Google OAuth client configuration.')

    flow = InstalledAppFlow.from_client_config(client_info, scopes=[DRIVE_SCOPE])
    credentials = flow.run_local_server(
        host='127.0.0.1',
        port=0,
        open_browser=True,
        access_type='offline',
        prompt='consent',
        success_message='BooStudy получил доступ к Google Drive. Можно закрыть эту вкладку.',
    )
    if not credentials.refresh_token:
        raise RuntimeError('Google did not provide an offline refresh token. Revoke the app and authorize again.')

    drive = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    folder = drive.files().get(fileId=args.folder_id, fields='id,name,mimeType').execute()
    if folder.get('mimeType') != 'application/vnd.google-apps.folder':
        raise RuntimeError('The selected Google Drive ID is not a folder.')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'oauth_client': client_info,
        'refresh_token': credentials.refresh_token,
        'folder_id': args.folder_id,
    }
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False)
    try:
        args.output.chmod(0o600)
    except OSError:
        pass
    print(f'Google Drive folder connected: {folder.get("name")}. Credentials saved to {args.output}.')


if __name__ == '__main__':
    main()
