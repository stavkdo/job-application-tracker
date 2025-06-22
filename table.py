import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials as cCredentials
import os
import re
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
import base64
from transformers.pipelines import pipeline
from transformers.models.auto.tokenization_auto import AutoTokenizer
from transformers.models.auto.modeling_auto import AutoModelForTokenClassification


def main():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.readonly"
    ]

    tokenizer = AutoTokenizer.from_pretrained("dslim/distilbert-NER")
    model = AutoModelForTokenClassification.from_pretrained("dslim/distilbert-NER")

    ner_model = pipeline("ner", model=model, tokenizer=tokenizer)
    
    creds = authenticate_user(SCOPES)

    client = gspread.authorize(creds)
    
    sheet = create_table(client)

    table_setup_old_mails(creds, sheet, ner_model)


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


def classify_email(subject, body, sender, ner_model):
    new_application = ".*(received your application)|(for applying)|(are interested in joining).*"
    not_accepted = ".*( is no longer open|did not select you for further consideration|met the requirements for this position|(decided to|will not be|we won’t be|we have chosen to) (move|moving|proceed|pursue)( forward)?( with)? (you|your candidacy|other candidates|another candidate|other applicants)?).*"
    position_name = ""
    company_name = ""
    


    try:
        # Combine subject and body for context
        email_content = f"Subject: {subject}\n\nBody: {body}"

        if re.search(new_application, email_content) and not re.search(not_accepted, email_content):
            classification = "Applied"
        else:
            classification = "Other" 

        match_comp = re.search(r"\b(?:at|in|from|with|by|company|organization|employer)[:\s]*([A-Z][a-z A-Z0-9&.,'\s]+(?:\s(?:Inc|LLC|Ltd|Corp|Co\.|Corporation))?)\b", email_content)
        print(match_comp)
        if match_comp:
            company_name = match_comp.group(1).strip() if match_comp else "N/A"

        if company_name == "N/A" and sender:
            company_name = sender
        
        match_pos = re.search(r"(applying to the )?(?:position|role|job|title)[:\s]*(?:of\s*)?([A-Z][- a-zA-Z0-9&.,'\s]+(?:\s(?:J)?)?)", email_content, re.IGNORECASE)
        print(match_pos)
        if match_pos:
            position_name = match_pos.group(1).strip() if match_pos else "N/A"

        print("Company:", company_name)
        print("Position:", position_name)

        # Return the classification and extracted information
        return classification, position_name, company_name

    except Exception as e:
        print(f"Error during classification: {e}")
        return None, None, None


def table_setup_old_mails(creds, sheet, ner_model):
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

            
                    classification, position_name, company_name = classify_email(subject, body, sender, ner_model)
                    if classification == "Applied":
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


