import os
import json
import re
import imaplib
import email
import requests
from datetime import datetime, timedelta
from email.header import decode_header

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = "sent_email_ids.json"
HEARTBEAT_FILE = "heartbeat_state.json"


# =========================
# STRICT BUSINESS KEYWORDS
# =========================

HIGH_KEYWORDS = [
    "ใบเสนอราคา",
    "quotation",
    "quote",
    "boq",
    "invoice",
    "payment",
    "contract",
    "agreement",
    "proposal",
    "purchase order",
    "approve",
    "approval",
    "urgent",
]

MEDIUM_KEYWORDS = [
    "sprinkler",
    "fire pump",
    "fire protection",
    "catalog",
    "drawing",
    "technical",
    "specification",
    "datasheet",
    "factory",
    "warehouse",
    "contractor",
    "consultant",
]

# คำพวกนี้ถ้าเจอ จะลดคะแนนแรง
PROMOTION_KEYWORDS = [
    "promotion",
    "discount",
    "sale",
    "webinar",
    "course",
    "unsubscribe",
    "newsletter",
    "special offer",
    "early bird",
    "limited offer",
    "gift",
    "credit",
    "shop",
    "class",
    "academy",
    "learn",
    "training",
    "invite",
    "invited",
    "business guide",
    "download",
    "save up to",
    "ส่วนลด",
    "หมดอายุ",
    "คลาสเรียน",
    "เพิ่มยอดขาย",
    "แคมเปญ",
]

# sender ที่ไม่ควรแจ้งเตือน ยกเว้นในอนาคตเราตั้ง whitelist เฉพาะ
HARD_IGNORE_SENDERS = [
    "temu",
    "coursera",
    "alison",
    "instagram",
    "tiktok",
    "shop.tiktok.com",
    "microsoftstore",
    "aia.co.th",
    "nfpa.org",
    "noreply@tm.openai.com",
    "notifications@github.com",
    "newsletter",
    "marketing",
]

# sender ที่เป็นระบบอัตโนมัติทั่วไป
AUTO_SENDERS = [
    "no-reply",
    "noreply",
    "donotreply",
    "do-not-reply",
    "notification",
    "notifications",
]


def html_escape(text):
    if text is None:
        return ""

    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def truncate_text(text, max_length=3500):
    if len(text) <= max_length:
        return text

    return text[:max_length] + "\n\n...[message truncated]"


def decode_text(value):
    if not value:
        return ""

    result = ""

    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            result += text.decode(charset or "utf-8", errors="ignore")
        else:
            result += text

    return result.strip()


def load_json_file(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_sent_ids():
    data = load_json_file(STATE_FILE, [])
    return set(data)


def save_sent_ids(sent_ids):
    save_json_file(STATE_FILE, list(sent_ids)[-1000:])


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    message = truncate_text(message, 3500)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(url, json=payload, timeout=20)

    if response.status_code != 200:
        print("Telegram error:", response.status_code, response.text)
        response.raise_for_status()


def extract_body(msg):
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/plain" and "attachment" not in disposition:
                try:
                    body += part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8",
                        errors="ignore"
                    )
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8",
                errors="ignore"
            )
        except Exception:
            body = ""

    return body.strip()


def extract_attachments(msg):
    attachments = []

    for part in msg.walk():
        filename = part.get_filename()

        if filename:
            filename = decode_text(filename)
            content_type = part.get_content_type()

            attachments.append({
                "filename": filename,
                "content_type": content_type,
            })

    return attachments


def has_pdf_or_url(subject, body, attachments):
    text = f"{subject} {body}".lower()

    if ".pdf" in text:
        return True

    if "ราชกิจจา" in text or "ratchakitcha" in text:
        return True

    for att in attachments:
        filename = att["filename"].lower()
        content_type = att["content_type"].lower()

        if filename.endswith(".pdf") or content_type == "application/pdf":
            return True

    return False


def contains_keyword(text, keyword):
    text = text.lower()
    keyword = keyword.lower()

    # ภาษาไทยและ phrase ยาว ใช้ contains ได้
    if any(ord(ch) > 127 for ch in keyword) or " " in keyword:
        return keyword in text

    # keyword อังกฤษสั้น/คำเดี่ยว ต้อง match เป็นคำจริงเท่านั้น
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text) is not None


def count_matches(text, keywords):
    matches = []

    for keyword in keywords:
        if contains_keyword(text, keyword):
            matches.append(keyword)

    return matches


def is_hard_ignore_sender(sender):
    sender_lower = sender.lower()

    for item in HARD_IGNORE_SENDERS:
        if item.lower() in sender_lower:
            return True

    return False


def is_auto_sender(sender):
    sender_lower = sender.lower()

    for item in AUTO_SENDERS:
        if item.lower() in sender_lower:
            return True

    return False


def score_email(sender, subject, body, attachments):
    text = f"{sender} {subject} {body}".lower()
    sender_lower = sender.lower()

    score = 0
    reasons = []

    high_matches = count_matches(text, HIGH_KEYWORDS)
    medium_matches = count_matches(text, MEDIUM_KEYWORDS)
    promotion_matches = count_matches(text, PROMOTION_KEYWORDS)

    for word in high_matches:
        score += 6
        reasons.append(f"พบ keyword สำคัญจริง: {word}")

    for word in medium_matches:
        score += 3
        reasons.append(f"พบ keyword งาน/เทคนิค: {word}")

    for word in promotion_matches:
        score -= 6
        reasons.append(f"มีลักษณะ promotion/newsletter: {word}")

    if attachments:
        score += 4
        reasons.append(f"มีไฟล์แนบ {len(attachments)} ไฟล์")

    if is_auto_sender(sender):
        score -= 4
        reasons.append("sender เป็นระบบอัตโนมัติ / no-reply")

    if not is_auto_sender(sender):
        score += 2
        reasons.append("sender ดูเป็นบุคคล/บริษัทจริง")

    # sender hard ignore ลดแรง
    if is_hard_ignore_sender(sender):
        score -= 10
        reasons.append("sender อยู่ใน hard ignore list")

    return score, reasons, high_matches, medium_matches, promotion_matches


def classify(sender, score, high_matches, medium_matches, promotion_matches, attachments):
    # ตัด sender ที่เป็น hard ignore ออกก่อน ยกเว้นมี keyword สำคัญจริงมาก
    if is_hard_ignore_sender(sender) and len(high_matches) == 0:
        return "IGNORE"

    # ถ้าเป็น promotion และไม่มี keyword สำคัญจริง ไม่ส่ง
    if len(promotion_matches) > 0 and len(high_matches) == 0:
        return "IGNORE"

    # ต้องมี high keyword อย่างน้อย 1 ตัว หรือ มี attachment + medium keyword
    has_real_business_signal = (
        len(high_matches) > 0 or
        (attachments and len(medium_matches) > 0)
    )

    if not has_real_business_signal:
        return "IGNORE"

    if score >= 10:
        return "HIGH"

    if score >= 7:
        return "MEDIUM"

    return "IGNORE"


def build_alert(sender, subject, date_text, level, score, reasons, attachments, pending):
    safe_sender = html_escape(sender)
    safe_subject = html_escape(subject)
    safe_date = html_escape(date_text)
    safe_level = html_escape(level)
    safe_score = html_escape(score)

    reason_text = "\n".join(
        [f"- {html_escape(r)}" for r in reasons[:8]]
    ) or "- ไม่พบเหตุผลเฉพาะ"

    if attachments:
        attachment_text = "\n".join(
            [
                f"- {html_escape(a['filename'])} ({html_escape(a['content_type'])})"
                for a in attachments[:5]
            ]
        )
    else:
        attachment_text = "ไม่มีไฟล์แนบ"

    pending_text = ""
    if pending:
        pending_text = (
            "\n\n⚠ <b>Pending Verification</b>\n"
            "พบ PDF / ไฟล์แนบ / URL ที่ควรตรวจสอบก่อนใช้งานจริง"
        )

    return f"""📧 <b>Important Email Alert</b>

<b>Level:</b> {safe_level}
<b>Score:</b> {safe_score}

<b>From:</b> {safe_sender}
<b>Subject:</b> {safe_subject}
<b>Date:</b> {safe_date}

<b>Reason:</b>
{reason_text}

<b>Attachments:</b>
{attachment_text}{pending_text}
"""


def build_heartbeat(total_checked, total_alerts):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""✅ <b>Email Monitoring Heartbeat</b>

Status: ONLINE
Checked emails: {total_checked}
Important alerts: {total_alerts}
Time: {now}

ไม่มีเมลสำคัญใหม่ที่ต้องแจ้งเตือน
"""


def should_send_daily_heartbeat():
    today = datetime.now().strftime("%Y-%m-%d")
    state = load_json_file(HEARTBEAT_FILE, {})

    last_heartbeat_date = state.get("last_heartbeat_date")

    if last_heartbeat_date == today:
        return False

    return True


def mark_daily_heartbeat_sent():
    today = datetime.now().strftime("%Y-%m-%d")

    state = {
        "last_heartbeat_date": today,
        "last_heartbeat_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    save_json_file(HEARTBEAT_FILE, state)


def main():
    required = [
        EMAIL_ADDRESS,
        EMAIL_APP_PASSWORD,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
    ]

    if not all(required):
        raise RuntimeError("Missing required secrets")

    sent_ids = load_sent_ids()

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    mail.select("inbox", readonly=True)

    # เช็คย้อนหลัง 1 วันพอ เพราะ workflow รันทุก 15 นาที
    since_date = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
    status, data = mail.search(None, f'(SINCE "{since_date}")')

    if status != "OK":
        raise RuntimeError("Cannot search inbox")

    email_ids = data[0].split()

    total_checked = 0
    total_alerts = 0

    for email_id in email_ids[-50:]:
        status, msg_data = mail.fetch(email_id, "(RFC822)")

        if status != "OK":
            continue

        msg = email.message_from_bytes(msg_data[0][1])

        message_id = msg.get("Message-ID") or email_id.decode()

        if message_id in sent_ids:
            continue

        sender = decode_text(msg.get("From", ""))
        subject = decode_text(msg.get("Subject", ""))
        date_text = decode_text(msg.get("Date", ""))

        body = extract_body(msg)
        attachments = extract_attachments(msg)

        total_checked += 1

        score, reasons, high_matches, medium_matches, promotion_matches = score_email(
            sender,
            subject,
            body,
            attachments
        )

        level = classify(
            sender=sender,
            score=score,
            high_matches=high_matches,
            medium_matches=medium_matches,
            promotion_matches=promotion_matches,
            attachments=attachments
        )

        pending = has_pdf_or_url(subject, body, attachments)

        if level != "IGNORE":
            alert = build_alert(
                sender=sender,
                subject=subject,
                date_text=date_text,
                level=level,
                score=score,
                reasons=reasons,
                attachments=attachments,
                pending=pending,
            )

            send_telegram(alert)
            total_alerts += 1

        sent_ids.add(message_id)

    if total_alerts == 0 and should_send_daily_heartbeat():
        send_telegram(build_heartbeat(total_checked, total_alerts))
        mark_daily_heartbeat_sent()

    save_sent_ids(sent_ids)

    mail.close()
    mail.logout()


if __name__ == "__main__":
    main()
