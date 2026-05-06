"""
drive_utils.py — Google Drive upload utility for FastAPI
─────────────────────────────────────────────────────────
Uses a Google Service Account to upload files to a shared
Google Drive folder, set public permissions, and return
a shareable link.

Required pip packages (add to requirements.txt):
    google-api-python-client
    google-auth
    google-auth-httplib2

Service account setup:
    1. Go to console.cloud.google.com → IAM & Admin → Service Accounts
    2. Create a service account → download JSON key
    3. On Render: store JSON contents as a Secret File at /etc/secrets/service-account.json
    4. Share your target Drive folder with the service account email (Editor access)

Environment variable (add to .env):
    GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
    (Get folder ID from the Drive URL: drive.google.com/drive/folders/<FOLDER_ID>)
"""

import os
import logging
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

# Path to service account JSON key (Render Secret File location)
SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_PATH",
    "/etc/secrets/service-account.json"
)

# Target Google Drive folder ID (set in .env or Render environment variables)
# Get from Drive URL: drive.google.com/drive/folders/<THIS_PART>
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# Google Drive API scopes required
SCOPES = ["https://www.googleapis.com/auth/drive"]


# ── Internal: Build authenticated Drive client ─────────────────────────────────

def _get_drive_service():
    """
    Builds and returns an authenticated Google Drive API service client.
    Raises FileNotFoundError if the service account JSON is missing.
    """
    sa_path = Path(SERVICE_ACCOUNT_FILE)
    if not sa_path.exists():
        raise FileNotFoundError(
            f"Service account key not found at: {SERVICE_ACCOUNT_FILE}\n"
            "→ On Render: add it as a Secret File at /etc/secrets/service-account.json\n"
            "→ Locally: set GOOGLE_SERVICE_ACCOUNT_PATH in your .env"
        )

    credentials = service_account.Credentials.from_service_account_file(
        str(sa_path),
        scopes=SCOPES
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return service


# ── Internal: Make uploaded file publicly readable ─────────────────────────────

def _make_public(service, file_id: str) -> None:
    """Sets the file permission to 'anyone with the link can view'."""
    permission = {
        "type": "anyone",
        "role": "reader",
    }
    service.permissions().create(
        fileId=file_id,
        body=permission,
        fields="id"
    ).execute()


# ── Public API ─────────────────────────────────────────────────────────────────

def upload_file(file_path: str, file_name: str, folder_id: str = None) -> str:
    """
    Upload a file to Google Drive and return its public shareable link.

    Args:
        file_path  : Absolute or relative path to the file on disk.
        file_name  : Name the file should have on Google Drive.
        folder_id  : (Optional) Override the default GOOGLE_DRIVE_FOLDER_ID.
                     Useful if you need to upload to different folders.

    Returns:
        A public URL string: https://drive.google.com/file/d/<id>/view?usp=sharing

    Raises:
        FileNotFoundError : If local file or service account JSON is missing.
        HttpError         : If the Drive API call fails.
        ValueError        : If no folder ID is configured.

    Example:
        from drive_utils import upload_file

        link = upload_file("/tmp/report.pdf", "Exam_Report_2024.pdf")
        print(link)
        # → https://drive.google.com/file/d/1aBcDeFg.../view?usp=sharing
    """
    # Validate local file
    local_path = Path(file_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local file not found: {file_path}")

    # Resolve target folder
    target_folder = folder_id or DRIVE_FOLDER_ID
    if not target_folder:
        raise ValueError(
            "No Google Drive folder ID configured.\n"
            "Set GOOGLE_DRIVE_FOLDER_ID in your .env file or pass folder_id argument."
        )

    # Detect MIME type (Google Drive handles most types automatically)
    import mimetypes
    mime_type, _ = mimetypes.guess_type(str(local_path))
    mime_type = mime_type or "application/octet-stream"

    logger.info(f"[DriveUpload] Uploading '{file_name}' ({mime_type}) to folder {target_folder}")

    try:
        service = _get_drive_service()

        # File metadata
        file_metadata = {
            "name": file_name,
            "parents": [target_folder],
        }

        # Upload
        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink"
        ).execute()

        file_id = uploaded.get("id")
        logger.info(f"[DriveUpload] Uploaded successfully. File ID: {file_id}")

        # Make public
        _make_public(service, file_id)
        logger.info(f"[DriveUpload] File made public.")

        # Return shareable link
        public_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        logger.info(f"[DriveUpload] Public link: {public_link}")
        return public_link

    except HttpError as e:
        logger.error(f"[DriveUpload] Google Drive API error: {e}")
        raise
    except Exception as e:
        logger.error(f"[DriveUpload] Unexpected error during upload: {e}")
        raise


def upload_file_object(file_bytes: bytes, file_name: str, folder_id: str = None) -> str:
    """
    Upload raw bytes (e.g. from FastAPI UploadFile) to Google Drive.

    Args:
        file_bytes : Raw file content as bytes.
        file_name  : Name to give the file on Drive.
        folder_id  : (Optional) Override default folder.

    Returns:
        Public shareable link string.

    Example (in a FastAPI route):
        @router.post("/upload")
        async def upload(file: UploadFile = File(...)):
            content = await file.read()
            link = upload_file_object(content, file.filename)
            return {"link": link}
    """
    import tempfile

    # Write bytes to a temp file, then upload using upload_file()
    suffix = Path(file_name).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        return upload_file(tmp_path, file_name, folder_id=folder_id)
    finally:
        # Always clean up temp file
        try:
            os.remove(tmp_path)
        except OSError:
            pass
