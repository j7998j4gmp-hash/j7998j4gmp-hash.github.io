
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

    
    roots = service.files().list(
        q="name = 'J-Quants' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id,name)",
    ).execute()["files"]

    if len(roots) != 1:
        raise RuntimeError("J-Quants folder not uniquely found")

    folders = service.files().list(
        q=f"name = '財務データ' and '{roots[0]['id']}' in parents and trashed = false",
        fields="files(id,name)",
    ).execute()["files"]

    if len(folders) != 1:
        raise RuntimeError("Financial folder not uniquely found")

    folder_id = folders[0]["id"]


    escaped = filename.replace("\\", "\\\\").replace("'", "\\'")
    result = service.files().list(
        q=f"name = '{escaped}' and '{folder_id}' in parents and trashed = false",
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
    # Recheck all dates in the last 15 days.
    today = datetime.now(JST).date()
    total_rows = 0
    saved_days = 0
    failed_dates = []

    for days_ago in range(14, -1, -1):
        date = (
            today - timedelta(days=days_ago)
        ).strftime("%Y-%m-%d")

        try:
            rows = get_financial_data(date)

            if not rows:
                print("No disclosures:", date)
                continue

            fields = list(dict.fromkeys(
                key for row in rows for key in row.keys()
            ))

            output = io.StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=fields
            )
            writer.writeheader()
            writer.writerows(rows)

            filename = f"jquants_financials_{date}.csv"

            upload_to_drive(
                filename,
                output.getvalue().encode("utf-8-sig")
            )

            print("Saved date:", date)
            print("Rows:", len(rows))

            total_rows += len(rows)
            saved_days += 1

        except Exception as error:
            print("FAILED:", date, type(error).__name__, str(error))
            failed_dates.append(date)

    print("Saved days:", saved_days)
    print("Total rows:", total_rows)

    if failed_dates:
        raise RuntimeError(
            "Failed dates: " + ", ".join(failed_dates)
        )


if __name__ == "__main__":
    main()

