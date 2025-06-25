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
from environs import env
import time
from difflib import SequenceMatcher
from dateutil.parser import parse
from datetime import datetime

env.read_env()


def main():
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/gmail.readonly"
    ]
    
    genai_client = genai.Client(api_key=env("GOOGLE_AI_API_KEY"))

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
        sheet.update_acell('D1', "First Update")
        sheet.update_acell('E1',"Last Update")
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
        NEW_JOB_APPLICATION = "new job application"
        REJECTION = "rejection"
        HOME_ASSIGMENT = "home assigment"
        INTERVIEW = "interview"
        JOB_OFFER = "job offer"
        NOT_JOB_RELATED = "not job related"
       
    response = genai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f'We are building a system for tracking the job application process in the Hi-Tech industry.\
                    Given the content of an email,\
                    classify the current status of the applicant in the hiring pipeline.\
                    there can be emails that are not related to the job search.\
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
                    the position should have a title like: intern, junior, software engineer, QA, ect.\
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
    all_messages = []
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
                all_messages.extend(inbox_messages["messages"])
            else:
                print("No messages found in All Mail.")

            next_page_token = inbox_messages.get("nextPageToken")
            if not next_page_token:
                break

        for message in reversed(all_messages):
                msg = service.users().messages().get(userId="me", id=message["id"]).execute()
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])
                subject = next((header["value"] for header in headers if header["name"] == "Subject"), "No Subject")
                date = next((header["value"] for header in headers if header["name"] == "Date"), "No Date")
                try:
                    date = date.split('(')[0]
                except Exception as e:
                    date = date
                finally:
                    date = parse(date)
                    date_str = date.strftime("%Y-%m-%d %H:%M:%S")
                

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
                not_companies = ["The open univesity", "Hackeriot", "GitHub", "Not specified"]
                classification = classify_email_LLM(genai_client, email_content)
                

                if classification == "new job application":
                    position_name, company_name = extract_entities_LLM(genai_client, email_content)
                    if company_name not in not_companies:
                        updates.append([position_name, company_name, classification, date_str, date_str])
                elif classification != "not job related":
                    position_name, company_name = extract_entities_LLM(genai_client, email_content)
                    if company_name not in not_companies:
                        updated = False
                        for lst in reversed(updates):
                            if (SequenceMatcher(None, lst[0], position_name).ratio() > 0.5 or position_name == "Not specified" or lst[0] == "Not specified")\
                                and (SequenceMatcher(None, lst[1], company_name).ratio() > 0.7):
                                lst[2] = classification
                                lst[4] = date_str
                                updated = True
                                break
                        if not updated:
                            updates.append([position_name, company_name, classification, date_str, date_str])
        # Perform a batch update to the sheet
        if updates:
            range_to_update = f"A{i}:E{len(updates) + i - 1}"  # Adjust the range based on the current row
            sheet.update(range_name=range_to_update, values=updates)
            i += len(updates)  # Increment the starting row for the next batch
            updates.clear()  # Clear the updates list

    except HttpError as error:
        print(f"An error occurred: {error}")
    finally:
        print("Processing complete.")



def daily_mail_routine(creds, sheet, model):
    pass




if __name__=="__main__":
    main()


