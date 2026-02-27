"""
Configuration — Interview Scheduling Agent
Copy this file to config.py and fill in your credentials.
"""

# ─────────────────────────────────────────
# LLM (Anthropic Claude)
# ─────────────────────────────────────────
ANTHROPIC_API_KEY = "your-anthropic-api-key"  # or set ANTHROPIC_API_KEY env var
LLM_MODEL = "claude-haiku-4-5-20251001"       # Fast & cheap for email parsing

# ─────────────────────────────────────────
# Email (SMTP + IMAP)
# ─────────────────────────────────────────
EMAIL_CONFIG = {
    # Gmail example — use an App Password, not your main password
    # (Google Account → Security → 2FA → App Passwords)
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "username": "bindupak11@gmail.com",
    "password": "wucx yurg amib bflo",
    "from_address": "scheduler@yourcompany.com",
    "from_name": "Interview Scheduling Assistant",
}

# ─────────────────────────────────────────
# Google Calendar
# ─────────────────────────────────────────
CALENDAR_CONFIG = {
    # Option A: Service Account (recommended for org-wide access)
    "type": "service_account",
    "service_account_file": "credentials/service_account.json",

    # Option B: OAuth2 (for single user)
    # "type": "oauth2",
    # "token_file": "credentials/token.json",
}

# ─────────────────────────────────────────
# Scheduling Rules
# ─────────────────────────────────────────
SCHEDULING_RULES = {
    "default_duration_minutes": 60,
    "working_hours_start": "09:00",
    "working_hours_end": "18:00",
    "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
    "days_ahead_to_check": 14,
    "max_slots_offered": 5,
    "buffer_between_meetings_minutes": 15,
    "poll_email_interval_seconds": 60,
}
