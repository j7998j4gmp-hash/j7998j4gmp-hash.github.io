
import os
import csv
import io
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

JST = timezone(timedelta(hours=9))
API_URL = "https://api.jquants.com/v2/fins/summary"


def get_financial_data(date):
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

    escaped = filename.replace("\\", "\\\\").replace("'", "\\'")
    result = service.files().list(
        q=f"name = '{escaped}' and trashed = false",
        fields="nextPageToken,files(id,name)",
        pageSize=100,
    ).execute()

    media = MediaIoBaseUpload(
        io.BytesIO(content),
        mimetype="text/csv",
        resumable=True,
    )

    if result.get("files"):
        service.files().update(
            fileId=result["files"][0]["id"],
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
    # Initial test: last 14 calendar days
    today = datetime.now(JST).date()

    for days_ago in range(0, 15):
        date = (
            today - timedelta(days=days_ago)
        ).strftime("%Y-%m-%d")

        rows = get_financial_data(date)

        if not rows:
            continue

        fields = list(dict.fromkeys(
            key for row in rows for key in row.keys()
        ))

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

        filename = f"jquants_financials_{date}.csv"

        upload_to_drive(
            filename,
            output.getvalue().encode("utf-8-sig"),
        )

        print("Disclosure date:", date)
        print("Rows:", len(rows))
        return

    print("No financial data found in the last 15 days")


if __name__ == "__main__":
    main()
