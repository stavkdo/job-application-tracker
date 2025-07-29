import gspread
from table_LLM import genai_client, table_setup_old_mails, authenticate_user, create_table, daily_mail_routine


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly"
]

def main():
    '''for test and right now for renewing the authentication'''
    creds = authenticate_user(SCOPES, False)
    client = gspread.authorize(creds)
    sheet = create_table(client)
    #local setup
    #table_setup_old_mails(creds, sheet, genai_client)
    #local update checkup if needed
    daily_mail_routine(creds=creds, sheet=sheet, genai_client=genai_client) 

    #local run to update daily
    #first test before gcp deploying
    #schedule.every().day.at("14:45").do(
    #    lambda: daily_mail_routine(creds=creds, sheet=sheet, genai_client=genai_client))
    #while True:
    #    schedule.run_pending()
    #    time.sleep(1)

if __name__=="__main__":
    main()