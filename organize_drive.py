
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

credentials = Credentials(
    token=None,
    refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scopes=SCOPES,
)
credentials.refresh(Request())
drive = build("drive", "v3", credentials=credentials)


def list_files(query):
    files = []
    token = None
    while True:
        result = drive.files().list(
            q=query,
            fields="nextPageToken,files(id,name,parents,mimeType)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        files.extend(result.get("files", []))
        token = result.get("nextPageToken")
        if not token:
            return files


def get_folder(name, parent=None):
    parent_query = (
        f"'{parent}' in parents"
        if parent else "'root' in parents"
    )
    query = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{name}' and {parent_query} "
        "and trashed = false"
    )
    folders = list_files(query)
    if folders:
        return folders[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent:
        metadata["parents"] = [parent]

    folder = drive.files().create(
        body=metadata, fields="id"
    ).execute()
    print("Created folder:", name)
    return folder["id"]


root = get_folder("J-Quants")
stock_folder = get_folder("株価データ", root)
financial_folder = get_folder("財務データ", root)

for prefix, destination in [
    ("jquants_stocks_", stock_folder),
    ("jquants_financials_", financial_folder),
]:
    files = list_files(
        f"name contains '{prefix}' and "
        "mimeType = 'text/csv' and trashed = false"
    )

    for file in files:
        if not file["name"].startswith(prefix):
            continue

        parents = file.get("parents", [])
        if destination in parents:
            print("Already organized:", file["name"])
            continue

        if not parents:
            print("Skipped (no parent):", file["name"])
            continue

        drive.files().update(
            fileId=file["id"],
            addParents=destination,
            removeParents=",".join(parents),
            fields="id,parents",
        ).execute()

        print("Moved:", file["name"])

print("Organization completed")
