import os
import imaplib
import requests
from datetime import datetime

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()


def main():
    if not EMAIL_ADDRESS:
        raise RuntimeError("Missing EMAIL_ADDRESS")

    if not EMAIL_APP_PASSWORD:
        raise RuntimeError("Missing EMAIL_APP_PASSWORD")

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    mail.select("inbox", readonly=True)

    status, data = mail.search(None, "ALL")

    if status != "OK":
        raise RuntimeError("Cannot search inbox")

    email_ids = data[0].split()
    total_emails = len(email_ids)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    message = f"""✅ <b>Email Bot Test Success</b>

Status: ONLINE
Gmail login: OK
Inbox checked: OK
Total emails found: {total_emails}
Time: {now}

ระบบเชื่อมต่อ Gmail และ Telegram สำเร็จแล้ว
"""

    send_telegram(message)

    mail.close()
    mail.logout()


if __name__ == "__main__":
    main()
