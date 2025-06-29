import os
import gspread
from table_LLM import genai_client, table_setup_old_mails, daily_mail_routine, authenticate_user, create_table
from flask import Flask, Request


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly"
]


app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def job_trigger(request: Request):
    creds = authenticate_user(SCOPES)
    client = gspread.authorize(creds)
    sheet = create_table(client)
    daily_mail_routine(creds=creds, sheet=sheet, genai_client=genai_client)
    print("executing job")
    return "Success", 200


