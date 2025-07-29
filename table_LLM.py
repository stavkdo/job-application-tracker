import gspread
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from typing import Any
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
import base64
from google import genai
import enum
from pydantic import BaseModel
from environs import env
from difflib import SequenceMatcher
from dateutil.parser import parse
from datetime import date, timedelta
import json


env.read_env()


genai_client = genai.Client(api_key=env("GOOGLE_AI_API_KEY"))

def create_table(client: gspread.Client) -> gspread.Worksheet:
    try:
        sheet = client.open("application tracker").sheet1
    except gspread.SpreadsheetNotFound:
        sheet = client.create("application tracker").sheet1
        sheet.update_acell('A1',"Position Name")
        sheet.update_acell('B1',"Company Name")
        sheet.update_acell('C1',"Current Stage")
        sheet.update_acell('D1', "First Update")
        sheet.update_acell('E1',"Last Update")
    finally: 
        return sheet


def authenticate_user(SCOPES: list[str], using_cloud) -> Any:
    creds = None

    secret_json_str = env("GOOGLE_CLIENT_SECRET_JSON")
    token_base64 = env("TOKEN_PICKLE_BASE64")

    with open("client_secret_temp.json", "w") as f:
        json.dump(json.loads(secret_json_str), f)

    with open("token.pickle", "wb") as token_file:
        token_file.write(base64.b64decode(token_base64))

    try:
        if os.path.exists("token.pickle"):
            with open("token.pickle", "rb") as token:
                creds = pickle.load(token)

        if (not creds or not creds.valid) and not using_cloud :
            flow = InstalledAppFlow.from_client_secrets_file("client_secret_temp.json", SCOPES)
            creds = flow.run_local_server(port=0, access_type='offline', include_granted_scopes='true')

            with open("token.pickle", "wb") as token:
                pickle.dump(creds, token)

    finally:
        if os.path.exists("client_secret_temp.json"):
            os.remove("client_secret_temp.json")
    print("creds done")
    return creds


def classify_email_LLM(genai_client: Any, email_content: str) -> str:

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


def extract_entities_LLM(genai_client: Any, email_content: str) -> tuple[str, str]:
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
    

def service_setup(creds: Any) -> tuple[None | Any, None | str]:
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
            return None, None
        
        return service, inbox_id
    
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None, None



def email_config(message: dict, service: Any) -> tuple[str, str]:
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

    return email_content, date_str


def list_of_emails(service: Any, inbox_id: str, after_date: str) -> list[dict]:
    all_messages: list[dict] = []
    # Fetch messages from "All Mail" with pagination
    print("Fetching messages from inbox:")
    next_page_token = None
    while True:
            inbox_messages = service.users().messages().list(
                userId="me", labelIds=[inbox_id], maxResults=50, pageToken=next_page_token, q=f"after: {after_date}"
            ).execute()
            if "messages" in inbox_messages:
                all_messages.extend(inbox_messages["messages"])
            else:
                print("No messages found in All Mail.")

            next_page_token = inbox_messages.get("nextPageToken")
            if not next_page_token:
                break
    return all_messages


def table_setup_old_mails(creds: Any, sheet: gspread.Worksheet, genai_client: Any) -> None:
    updates = []  # Collect all updates in a list
    free_index = 2 #first free index in the table
    all_messages = []

    try:
        service, inbox_id = service_setup(creds)
        if service and inbox_id:
            all_messages = list_of_emails(service, inbox_id, "2024/09/01")

        if all_messages:
            for message in reversed(all_messages):
                    
                    email_content, date_str = email_config(message, service)
                    
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
            range_to_update = f"A{free_index}:E{len(updates) + free_index - 1}"  # Adjust the range based on the current row
            sheet.update(range_name=range_to_update, values=updates)
            free_index += len(updates)  # Increment the starting row for the next batch
            updates.clear()  # Clear the updates list

    except HttpError as error:
        print(f"An error occurred: {error}")
    finally:
        print("Processing complete.")
    


def daily_mail_routine(*, creds: Any, sheet: gspread.Worksheet, genai_client: Any) -> None:
    not_companies = ["The open univesity", "Hackeriot", "GitHub", "Not specified"]
    today_messages = []
    updates = []
    list_of_sheet_values = sheet.get_all_values() #one request to API, getting all info
    today = date.today()
    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y/%m/%d")
    first_empty_cell = len(list_of_sheet_values) + 1
    

    service, inbox_id = service_setup(creds)
    if service and inbox_id:
            today_messages = list_of_emails(service, inbox_id, yesterday_str) #getting today's messages from gmail
    if today_messages:
        for message in reversed(today_messages):
                    email_content, date_str = email_config(message, service)
                    classification = classify_email_LLM(genai_client, email_content)
                    if classification == "new job application":
                        position_name, company_name = extract_entities_LLM(genai_client, email_content)
                        if company_name not in not_companies:
                            updates.append([position_name, company_name, classification, date_str, date_str])
                    elif classification != "not job related":
                        position_name, company_name = extract_entities_LLM(genai_client, email_content)
                        if company_name not in not_companies:
                            for lst in reversed(list_of_sheet_values):
                                updated = False
                                if (SequenceMatcher(None, lst[0], position_name).ratio() > 0.5 or position_name == "Not specified" or lst[0] == "Not specified")\
                                    and (SequenceMatcher(None, lst[1], company_name).ratio() > 0.7):
                                    lst[2] = classification
                                    lst[4] = date_str
                                    updated = True
                                    break
                            if not updated:
                                updates.append([position_name, company_name, classification, date_str, date_str])
        if updates:
            range_to_update = f"A{first_empty_cell}:E{len(updates) + first_empty_cell - 1}"  # Adjust the range based on the current row
            sheet.update(range_name=range_to_update, values=updates)
            first_empty_cell += len(updates)  # Increment the starting row for the next batch
            updates.clear()
    print("routine done")