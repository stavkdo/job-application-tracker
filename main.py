import functions_framework
import gspread
from table_LLM import genai_client, daily_mail_routine, authenticate_user, create_table


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly"
]



@functions_framework.http
def job_trigger(requst):
    creds = authenticate_user(SCOPES)
    client = gspread.authorize(creds)
    sheet = create_table(client)
    daily_mail_routine(creds=creds, sheet=sheet, genai_client=genai_client)
    print("executing job")
    return "Success", 200


    