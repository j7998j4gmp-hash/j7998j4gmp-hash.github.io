
import os
import csv
import io
import json
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

JST = timezone(timedelta(hours=9))
API_URL = "https://api.jquants.com/v2/equities/bars/daily"

def get_stock_data(date):
    rows = []
    params = {"date": date}

    while True:
        response = requests.get(
            API_URL,
            headers={"x-api-key": os.environ["JQUANTS_API_KEY"]},
            params=params,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        rows.extend(result.get("data", []))

        key = result.get("pagination_key")
        if not key:
            break
        params["pagination_key"] = key

    return rows

def upload_to_drive(filename, content):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload

    credentials = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    credentials.refresh(Request())

    service = build("drive", "v3", credentials=credentials)

    
    # Find the J-Quants stock data folder.
    roots = service.files().list(
        q="name = 'J-Quants' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id,name)",
    ).execute()["files"]

    if len(roots) != 1:
        raise RuntimeError("J-Quants folder not uniquely found")

    folders = service.files().list(
        q=f"name = '株価データ' and '{roots[0]['id']}' in parents and trashed = false",
        fields="files(id,name)",
    ).execute()["files"]

    if len(folders) != 1:
        raise RuntimeError("Stock folder not uniquely found")

    folder_id = folders[0]["id"]


    # Search only for files visible to this OAuth application.
    escaped = filename.replace("\\", "\\\\").replace("'", "\\'")
    result = service.files().list(
        q=f"name = '{escaped}' and '{folder_id}' in parents and trashed = false",
        fields="files(id,name),nextPageToken",
        pageSize=100,
    ).execute()

    media = MediaIoBaseUpload(
        io.BytesIO(content),
        mimetype="text/csv",
        resumable=True,
    )

    if result.get("files"):
        file_id = result["files"][0]["id"]
        service.files().update(
            fileId=file_id,
            media_body=media,
        ).execute()
        print("Updated:", filename)
    else:
        service.files().create(
            body={
    "name": filename,
    "mimeType": "text/csv",
    "parents": [folder_id],
},
            media_body=media,
            fields="id",
        ).execute()
        print("Created:", filename)

def main():

    # Search the most recent seven calendar days.
    today = datetime.now(JST).date()
    rows = []
    date = None

    for days_ago in range(0, 8):
        candidate = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        rows = get_stock_data(candidate)

        if rows:
            date = candidate
            print("Latest available trading date:", date)
            break

    if date is None:
        print("No stock data found in the last seven days")
        return

    if not rows:
        print("No stock data for", date)
        return

    fields = list(dict.fromkeys(
        key for row in rows for key in row.keys()
    ))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

    filename = f"jquants_stocks_{date}.csv"
    upload_to_drive(filename, output.getvalue().encode("utf-8-sig"))
    print("Rows:", len(rows))

if __name__ == "__main__":
    main()
