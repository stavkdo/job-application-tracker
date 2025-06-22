from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import os
import pickle

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",  # Gmail API (read-only)
    "https://www.googleapis.com/auth/spreadsheets",   # Sheets API
    "https://www.googleapis.com/auth/drive"           # Drive API
]

def authenticate_user():
    creds = None
    # Check if token.pickle exists (to store user credentials)
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # If no valid credentials, prompt the user to log in
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json", SCOPES
        )
        creds = flow.run_local_server(port=0)

        # Save the credentials for future use
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return creds

def read_emails():
    try:
        # Authenticate the user
        creds = authenticate_user()

        # Build the Gmail API service
        service = build("gmail", "v1", credentials=creds)

        # Get the list of messages in the user's inbox
        results = service.users().messages().list(userId="me", maxResults=10).execute()
        messages = results.get("messages", [])

        if not messages:
            print("No messages found.")
            return

        print("Messages:")
        for message in messages:
            # Get the details of each message
            msg = service.users().messages().get(userId="me", id=message["id"]).execute()
            print(f"Message ID: {message['id']}")
            print(f"Snippet: {msg['snippet']}")
            print("-" * 50)

    except HttpError as error:
        print(f"An error occurred: {error}")

def read_drive_files_and_sheet_data():
    try:
        # Authenticate the user
        creds = authenticate_user()

        # Build the Sheets API service
        sheets_service = build("sheets", "v4", credentials=creds)

        # Example: Read data from a Google Sheet
        spreadsheet_id = "application tracker"
        range_name = "Sheet1!A1:D10"  # desired range
        sheet_data = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_name
        ).execute()
        print("Sheet Data:", sheet_data.get("values", []))

    except HttpError as error:
        print(f"An error occurred: {error}")

# Call the function to read emails
read_emails()

# Call the function to read files from Google Drive and data from Google Sheets
read_drive_files_and_sheet_data()