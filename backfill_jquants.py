
import os
import csv
import io
import time
from datetime import date, timedelta

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

BASE = "https://api.jquants.com/v2"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

START = date.fromisoformat(os.environ["START_DATE"])
END = date.fromisoformat(os.environ["END_DATE"])
KIND = os.environ["DATA_KIND"]

if KIND not in ("stocks", "financials"):
    raise ValueError("DATA_KIND must be stocks or financials")

if END < START or (END - START).days > 31:
    raise ValueError("Select a range of 1 to 32 calendar days")

if END > date.today():
    raise ValueError("END_DATE must not be in the future")

API_PATH = {
    "stocks": "/equities/bars/daily",
    "financials": "/fins/summary",
}[KIND]

PREFIX = {
    "stocks": "jquants_stocks_",
    "financials": "jquants_financials_",
}[KIND]

FOLDER_NAME = {
    "stocks": "株価データ",
    "financials": "財務データ",
}[KIND]

session = requests.Session()
session.headers.update({
    "x-api-key": os.environ["JQUANTS_API_KEY"]
})


def api_get(params):
    for attempt in range(6):
        try:
            response = session.get(
                BASE + API_PATH,
                params=params,
                timeout=90,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                delay = min(60, 2 ** attempt * 3)
                print("Retry API:", response.status_code)
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException:
            if attempt == 5:
                raise
            time.sleep(min(60, 2 ** attempt * 3))

    raise RuntimeError("API retry limit reached")


def fetch_rows(day):
    rows = []
    params = {"date": day}

    while True:
        result = api_get(params)
        rows.extend(result.get("data", []))
        key = result.get("pagination_key")

        if not key:
            return rows

        params["pagination_key"] = key


def drive_service():
    credentials = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return build("drive", "v3", credentials=credentials)


drive = drive_service()


def list_files(query):
    results = []
    token = None

    while True:
        page = drive.files().list(
            q=query,
            fields="nextPageToken,files(id,name)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        results.extend(page.get("files", []))
        token = page.get("nextPageToken")

        if not token:
            return results


def find_folder(name, parent=None):
    escaped = name.replace("'", "\\'")
    parent_filter = (
        f"'{parent}' in parents"
        if parent else "'root' in parents"
    )
    matches = list_files(
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{escaped}' "
        f"and {parent_filter} and trashed = false"
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one folder named {name}, found {len(matches)}"
        )
    return matches[0]["id"]


root_id = find_folder("J-Quants")
folder_id = find_folder(FOLDER_NAME, root_id)

existing = {
    item["name"]
    for item in list_files(
        f"'{folder_id}' in parents and trashed = false"
    )
}


def save_csv(filename, rows):
    fields = list(dict.fromkeys(
        key for row in rows for key in row
    ))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

    media = MediaIoBaseUpload(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        resumable=True,
    )

    drive.files().create(
        body={
            "name": filename,
            "mimeType": "text/csv",
            "parents": [folder_id],
        },
        media_body=media,
        fields="id",
    ).execute()

    existing.add(filename)


def main():
    current = START
    saved = 0
    skipped = 0
    empty = 0
    failures = []

    while current <= END:
        day = current.isoformat()
        current += timedelta(days=1)

        if KIND == "stocks" and date.fromisoformat(day).weekday() >= 5:
            continue

        filename = PREFIX + day + ".csv"

        if filename in existing:
            print("SKIP existing:", filename)
            skipped += 1
            continue

        try:
            rows = fetch_rows(day)

            if not rows:
                print("NO DATA:", day)
                empty += 1
                continue

            save_csv(filename, rows)
            saved += 1
            print("SAVED:", filename, "Rows:", len(rows))

        except Exception as error:
            print("FAILED:", day, repr(error))
            failures.append(day)

        time.sleep(1)

    print("Saved:", saved)
    print("Skipped existing:", skipped)
    print("No data:", empty)
    print("Failed:", len(failures))

    if failures:
        raise RuntimeError("Failed dates: " + ", ".join(failures))


if __name__ == "__main__":
    main()
