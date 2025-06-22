import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials as cCredentials
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
import base64
from google import genai
import enum
from pydantic import BaseModel





def main():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.readonly"
    ]

    genai_client = genai.Client(api_key=os.environ["GOOGLE_AI_API_KEY"])

    creds = authenticate_user(SCOPES)

    client = gspread.authorize(creds)
    
    sheet = create_table(client)

    table_setup_old_mails(creds, sheet, genai_client)


def create_table(client):
    try:
        sheet = client.open("application tracker").sheet1
    except gspread.SpreadsheetNotFound:
        sheet = client.create("application tracker").sheet1
    finally: 
        sheet.update_acell('A1',"Position Name")
        sheet.update_acell('B1',"Company Name")
        sheet.update_acell('C1',"Current Stage")
        sheet.update_acell('D1',"Last Update")
        return sheet


def authenticate_user(SCOPES):
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

def classify_email_LLM(genai_client, email_content):

    class Status(enum.Enum):
        APPLIED_TO_NEW_JOB = "applied to a job"
        REJECTION = "rejection"
        HOME_ASSIGMENT = "home assigment"
        INTERVIEW = "interview"
        JOB_OFFER = "job offer"
        NOT_JOB_RELATED = "not job related"
       
    response = genai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f'You are assisting in a system for tracking the job application process.\
                    Based on the content of the following email,\
                    classify its status into one of the categories\
                    email: {email_content}',
        config={
        'response_mime_type': 'text/x.enum',
        'response_schema': Status,
        },
    )
    print(response.text)
    return response.text


def extract_entities_LLM(genai_client, email_content):
    class Names(BaseModel):
        position_name: str
        comapny_name: str

    response = genai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f'Extract the job position and company name mentioned in the following email.\
                    If either detail is missing, write "Not specified".\
                    Email content: {email_content}',
        config={
        "response_mime_type": "application/json",
        "response_schema": Names,
        },
    )
    print(response.text)
    names: Names = response.parsed
    return names.position_name, names.comapny_name
    


def table_setup_old_mails(creds, sheet, genai_client):
    try:
        # Call the Gmail API
        service = build("gmail", "v1", credentials=creds)

        # Get the list of labels
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        # Find the label ID for "All Mail"
        label_ids = {label["name"]: label["id"] for label in labels}
        inbox_id = label_ids.get("INBOX")

        if not inbox_id:
            print("inbox label not found.")
            return

        # Fetch messages from "All Mail" with pagination
        print("Fetching messages from inbox:")
        next_page_token = None
        updates = []  # Collect all updates in a list
        i = 2

        while True:
            inbox_messages = service.users().messages().list(
                userId="me", labelIds=[inbox_id], maxResults=50, pageToken=next_page_token, q="after: 2024/09/01"
            ).execute()

            if "messages" in inbox_messages:
                for message in inbox_messages["messages"]:
                    msg = service.users().messages().get(userId="me", id=message["id"]).execute()
                    payload = msg.get("payload", {})
                    headers = payload.get("headers", [])
                    subject = next((header["value"] for header in headers if header["name"] == "Subject"), "No Subject")
                    date = next((header["value"] for header in headers if header["name"] == "Date"), "No Date")
                    sender = next((header["value"] for header in headers if header["name"] == "From"), "No Sender")
                    sender_name = sender.split('@')[0].split('<')[0]

                    body = ""
                    if "body" in payload and "data" in payload["body"]:
                        body = payload["body"]["data"]
                    elif "parts" in payload:
                        for part in payload["parts"]:
                            if "body" in part and "data" in part["body"]:
                                body = part["body"]["data"]
                                break

                    # Decode the body if it's Base64 encoded
                    if body:
                        try:
                            body = base64.urlsafe_b64decode(body).decode("utf-8")
                        except UnicodeDecodeError:
                            try:
                                body = base64.urlsafe_b64decode(body).decode("ISO-8859-1")
                            except Exception as e:
                                print(f"Failed to decode email body: {e}")
                                body = ""  # Set body to an empty string if decoding fails


                    email_content = f"Subject: {subject}\n\nBody: {body}"
            
                    classification = classify_email_LLM(genai_client, email_content)
                    
                    if classification == "applied to a job":
                        position_name, company_name = extract_entities_LLM(genai_client, email_content)
                        updates.append([position_name or "N/A", company_name or "N/A", classification, date])

                # Perform a batch update to the sheet
                if updates:
                    range_to_update = f"A{i}:D{len(updates) + i - 1}"  # Adjust the range based on the current row
                    sheet.update(range_name=range_to_update, values=updates)
                    i += len(updates)  # Increment the starting row for the next batch
                    updates.clear()  # Clear the updates list

                next_page_token = inbox_messages.get("nextPageToken")
                if not next_page_token:
                    break

            else:
                print("No messages found in All Mail.")

    except HttpError as error:
        print(f"An error occurred: {error}")
    finally:
        print("Processing complete.")


if __name__=="__main__":
    main()


