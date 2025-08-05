# Job Application Email Tracker with Google Sheets & Gemini LLM

This Python project automates the process of tracking job application emails by parsing their content using Google's Gemini LLM and organizing the extracted data in a structured Google Sheet.

## 📌 Features

- ✅ Connects to Gmail inbox to fetch job application-related emails.
- 🧠 Uses **Gemini (Google's LLM)** to intelligently analyze email content and extract:
  - Job title
  - Company name
  - Date of application
  - Application status (e.g., rejected, follow-up, interview)
- 📄 Automatically updates a **Google Sheet** with the extracted information.
- 🔁 Designed to run periodically using **Google Cloud Functions** and **Cloud Scheduler**.

## 🧰 Technologies Used

- **Python 3**
- **Gmail API** — for email access
- **Google Gemini API** — for LLM-based natural language parsing
- **Google Sheets API** — for real-time spreadsheet updates
- **Google Cloud Functions & Scheduler** — for automation

## 📁 Example Output

| Job Title       | Company     | Date Sent | Status     |
|-----------------|-------------|-----------|------------|
| Backend Dev     | Acme Corp   | 2025-08-01| Rejected   |
| Data Analyst    | DataX       | 2025-08-02| Follow-up  |

## 📌 Project Goals

- Centralize and track all job application activity in one place
- Reduce manual spreadsheet updates
- Experiment with LLMs (Gemini) for practical document understanding tasks
- Gain hands-on experience with Google Cloud automation and APIs

## 👤 Author

**Stav Kdoshim**  
📧 stavkd04@gmail.com
