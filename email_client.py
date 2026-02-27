"""
Email Client — SMTP + IMAP integration
Handles sending interview emails and parsing inbound replies.
"""

import smtplib
import imaplib
import email
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedEmail:
    sender: str
    subject: str
    body: str
    request_id: Optional[str]
    received_at: datetime


class EmailClient:
    """
    SMTP for sending, IMAP for polling inbound replies.
    Configure with Gmail, Outlook, or any SMTP/IMAP provider.
    """

    def __init__(self, config: dict):
        self.smtp_host = config["smtp_host"]
        self.smtp_port = config.get("smtp_port", 587)
        self.imap_host = config["imap_host"]
        self.imap_port = config.get("imap_port", 993)
        self.username = config["username"]
        self.password = config["password"]
        self.from_name = config.get("from_name", "Interview Scheduling Assistant")
        self.from_address = config["from_address"]
        self.sent_emails = []  # track sent emails for summary

    # ─────────────────────────────────────────
    # Send email via SMTP
    # ─────────────────────────────────────────
    def send(self, to: str, subject: str, body: str, reply_to: str = None) -> bool:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to

        # Plain text part
        msg.attach(MIMEText(body, "plain"))

        # HTML part (auto-generate from plain text)
        html_body = self._plain_to_html(body)
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.from_address, to, msg.as_string())
            print(f"[Email] ✅ Sent to {to}: {subject}")
            self.sent_emails.append({"to": to, "subject": subject})
            return True
        except smtplib.SMTPException as e:
            print(f"[Email] ❌ Failed to send to {to}: {e}")
            return False

    # ─────────────────────────────────────────
    # Poll IMAP for new replies
    # ─────────────────────────────────────────
    def fetch_new_replies(self) -> list[ParsedEmail]:
        """
        Fetch ONLY scheduling reply emails — emails that contain
        a [Request ID: req_...] in subject or body.
        Ignores all other inbox emails (newsletters, notifications, etc.)
        """
        parsed_emails = []
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port) as mail:
                mail.login(self.username, self.password)
                mail.select("INBOX")

                # ONLY search for emails with "Request ID" or "req_" in subject
                # This filters out Quora, Udemy, and all other newsletters
                search_criteria = [
                    'SUBJECT "Interview Scheduling"',
                    'SUBJECT "req_"',
                    'SUBJECT "Interview Confirmed"',
                ]

                candidate_msg_ids = set()
                for criteria in search_criteria:
                    _, msg_ids = mail.search(None, criteria)
                    if msg_ids[0]:
                        for mid in msg_ids[0].split():
                            candidate_msg_ids.add(mid)

                print(f"[Email] Found {len(candidate_msg_ids)} scheduling email(s) to check")

                for msg_id in candidate_msg_ids:
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    parsed = self._parse_raw_email(raw)
                    if not parsed:
                        continue

                    # Skip emails we sent ourselves
                    if parsed.sender.lower() == self.from_address.lower():
                        mail.store(msg_id, "+FLAGS", "\\Seen")
                        continue

                    # Only process if it has a valid request ID
                    if parsed.request_id:
                        parsed_emails.append(parsed)
                        print(f"[Email] ✅ Scheduling reply from {parsed.sender} | request_id={parsed.request_id}")
                    else:
                        print(f"[Email] ⚠️  Skipping email from {parsed.sender} — no request ID found")

                    # Mark as read
                    mail.store(msg_id, "+FLAGS", "\\Seen")

        except imaplib.IMAP4.error as e:
            print(f"[Email] IMAP error: {e}")
        except Exception as e:
            print(f"[Email] Unexpected error in fetch_new_replies: {e}")

        return parsed_emails

    def _parse_raw_email(self, raw_email: bytes) -> Optional[ParsedEmail]:
        msg = email.message_from_bytes(raw_email)

        sender = email.utils.parseaddr(msg["From"])[1]

        # Decode subject safely
        try:
            subject_parts = decode_header(msg.get("Subject", ""))
            subject = ""
            for part, enc in subject_parts:
                if isinstance(part, bytes):
                    subject += part.decode(enc or "utf-8", errors="replace")
                else:
                    subject += str(part)
        except Exception:
            subject = str(msg.get("Subject", ""))

        # Extract full body including quoted text (request ID may be in quoted section)
        body = self._extract_body(msg)

        # Try to find request ID anywhere in body + subject
        request_id = self._extract_request_id(body + " " + subject)

        if not request_id:
            print(f"[Email] ⚠️  No request ID found in email from {sender} | subject: {subject[:60]}")

        return ParsedEmail(
            sender=sender,
            subject=subject,
            body=body,
            request_id=request_id,
            received_at=datetime.now(),
        )

    def _extract_body(self, msg) -> str:
        """
        Extract ALL text from email — both the reply and the quoted original.
        We need the quoted part because the Request ID is in the original email.
        """
        body_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text = part.get_payload(decode=True).decode(charset, errors="replace")
                        body_parts.append(text)
                    except Exception:
                        pass
                elif content_type == "text/html" and not body_parts:
                    # Fallback to HTML if no plain text found
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html = part.get_payload(decode=True).decode(charset, errors="replace")
                        # Strip HTML tags roughly to get text
                        text = re.sub(r"<[^>]+>", " ", html)
                        body_parts.append(text)
                    except Exception:
                        pass
        else:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body_parts.append(msg.get_payload(decode=True).decode(charset, errors="replace"))
            except Exception:
                pass

        return "\n".join(body_parts)

    def _extract_request_id(self, text: str) -> Optional[str]:
        """
        Extract request ID from email text.
        Handles multiple formats Gmail might use when quoting/forwarding.
        """
        if not text:
            return None

        # Pattern 1: exact format  [Request ID: req_abc123]
        match = re.search(r"\[Request\s+ID:\s*(req_[\w\-]+)\]", text, re.IGNORECASE)
        if match:
            return match.group(1)

        # Pattern 2: just the ID on its own line  req_abc123
        match = re.search(r"\b(req_[\w\-]+)\b", text)
        if match:
            return match.group(1)

        # Pattern 3: URL-encoded or broken across lines
        match = re.search(r"req[_\-]([\w\-]+)", text, re.IGNORECASE)
        if match:
            return "req_" + match.group(1)

        return None

    def _plain_to_html(self, text: str) -> str:
        """Convert plain text email to basic HTML."""
        lines = text.split("\n")
        html_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("•"):
                html_lines.append(f"<li>{stripped[1:].strip()}</li>")
            elif stripped == "":
                html_lines.append("<br>")
            else:
                html_lines.append(f"<p>{stripped}</p>")
        return f"""
<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #333; max-width: 600px;">
{''.join(html_lines)}
</body></html>"""


# ─────────────────────────────────────────
# Configuration presets
# ─────────────────────────────────────────

def gmail_config(username: str, app_password: str) -> dict:
    return {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "username": username,
        "password": app_password,
        "from_address": username,
    }


def outlook_config(username: str, password: str) -> dict:
    return {
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "username": username,
        "password": password,
        "from_address": username,
    }