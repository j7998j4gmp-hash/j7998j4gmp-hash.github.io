
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

    # Search only for files visible to this OAuth application.
    escaped = filename.replace("\\", "\\\\").replace("'", "\\'")
    result = service.files().list(
        q=f"name = '{escaped}' and trashed = false",
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
            body={"name": filename, "mimeType": "text/csv"},
            media_body=media,
            fields="id",
        ).execute()
        print("Created:", filename)

def main():
    # Start with the previous calendar day.
    date = "2026-11-20"
    rows = get_stock_data(date)

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
