#take2:
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



def main():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.readonly"
    ]

    model = pipeline("ner", model="dslim/bert-large-NER", grouped_entities=True)

    classifier = pipeline("zero-shot-classification", model='cross-encoder/nli-MiniLM2-L6-H768')

    
    creds = authenticate_user(SCOPES)

    client = gspread.authorize(creds)
    
    sheet = create_table(client)

    table_setup_old_mails(creds, sheet, model, classifier)


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


def classify_email(sender, subject, body, ner_model, classifier):
    email_content = f"Sender: {sender}\n\n Subject: {subject}\n\nBody: {body}"
    email_label_classification_table = ["Job Application", "Rejection", "Job Interview", "Job Offer", "Home Assigment", "Not Job Related"]

    try:
        classification = classifier(email_content, email_label_classification_table)
        print(f"Classification: {classification}")

        # Perform named entity recognition (NER)
        entities = ner_model(email_content)
        print("Entities:", entities)  # Debugging

        company = None
        position = None
        date = None

        for entity in entities:
            print(f"{entity['entity_group']}: {entity['word']}")
            label = entity["entity_group"]
            text = entity["word"]

        if label == "ORG" and company is None:
            company_name = text

        elif label == "DATE" and date is None:
            email_date = text

        elif label == "MISC" and position is None:
            if any(word in text.lower() for word in ["Engineer", "Developer", "Developing", "Student", "Analyst", "Intern", "QA", "Engineering"]):
                position_name = text

        print("Company:", company_name)
        print("Position:", position_name)
        print("Date:", email_date)

        # Return the classification and extracted information
        return classification, position_name, company_name, email_date

    except Exception as e:
        print(f"Error during classification: {e}")
        return None, None, None, None


def combine_entities(entities):
    """
    Combines consecutive tokens with the same entity type into a single entity.
    
    Args:
        entities: A list of entities returned by the NER model.
    
    Returns:
        A list of combined entities.
    """
    combined = []
    current_entity = None
    current_text = ""

    for entity in entities:
        # Check if the current entity matches the previous one (B-XXX or I-XXX)
        if current_entity and (entity["entity"].startswith("I-") or entity["entity"] == current_entity):
            current_text += entity['word'].strip(" #")  # Append the word without extra spaces
        else:
            # Save the previous entity if it exists
            if current_entity:
                combined.append({"entity": current_entity, "word": current_text.strip()})
            # Start a new entity
            current_entity = entity["entity"]
            current_text = entity["word"].strip(" #")

    # Add the last entity
    if current_entity:
        combined.append({"entity": current_entity, "word": current_text.strip()})

    return combined




def table_setup_old_mails(creds, sheet, ner_model, classifier):
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

                    # Use LLM to classify the email and extract additional information
                    classification, position_name, company_name, email_date = classify_email(sender, subject, body, ner_model, classifier)
                    if classification == "Job Application":
                        updates.append([position_name or "N/A", company_name or "N/A", classification, email_date or date])

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