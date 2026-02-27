"""
Calendar Client — Google Calendar API Integration
Fetches availability and creates confirmed interview events.
"""

from datetime import datetime, timedelta, time
from typing import Optional
import json

# Google Calendar SDK (install: pip install google-auth google-auth-oauthlib google-api-python-client)
try:
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    print("[Calendar] Warning: google-api-python-client not installed. Using mock mode.")


class CalendarClient:
    """
    Google Calendar integration.
    Supports both OAuth2 (user accounts) and Service Account (org-wide) auth.
    """

    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(self, auth_config: dict):
        self.auth_config = auth_config
        self.services: dict = {}  # Cache of {email: service}
        self.working_hours_start = time(9, 0)   # 9:00 AM
        self.working_hours_end = time(18, 0)    # 6:00 PM
        self.working_days = {0, 1, 2, 3, 4}    # Mon–Fri (weekday() values)

    def _get_service(self, email: str = None):
        """Get or create a Google Calendar API service instance."""
        if not GOOGLE_AVAILABLE:
            return MockCalendarService()

        cache_key = email or "default"
        if cache_key in self.services:
            return self.services[cache_key]

        auth_type = self.auth_config.get("type", "service_account")

        if auth_type == "service_account":
            creds = service_account.Credentials.from_service_account_file(
                self.auth_config["service_account_file"],
                scopes=self.SCOPES,
            )
            if email:
                # Domain-wide delegation — impersonate the user
                creds = creds.with_subject(email)
        elif auth_type == "oauth2":
            creds = Credentials.from_authorized_user_file(
                self.auth_config["token_file"], self.SCOPES
            )
        else:
            raise ValueError(f"Unknown auth type: {auth_type}")

        service = build("calendar", "v3", credentials=creds)
        self.services[cache_key] = service
        return service

    # ─────────────────────────────────────────
    # Get available slots for a user
    # ─────────────────────────────────────────
    def get_available_slots(
        self,
        email: str,
        duration_minutes: int = 60,
        days_ahead: int = 14,
        exclude_slots: list = None,
    ) -> list[dict]:
        """
        Return list of free slots within working hours for the next N days.
        Uses Google's freebusy API to query existing commitments.
        """
        service = self._get_service(email)
        now = datetime.utcnow()
        time_max = now + timedelta(days=days_ahead)

        # Query freebusy
        body = {
            "timeMin": now.isoformat() + "Z",
            "timeMax": time_max.isoformat() + "Z",
            "items": [{"id": email}],
        }

        try:
            freebusy = service.freebusy().query(body=body).execute()
            busy_periods = freebusy.get("calendars", {}).get(email, {}).get("busy", [])
        except Exception as e:
            print(f"[Calendar] freebusy query failed: {e}")
            busy_periods = []

        busy = [
            (self._parse_dt(b["start"]), self._parse_dt(b["end"]))
            for b in busy_periods
        ]

        # Generate candidate slots within working hours
        slots = []
        current = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)

        while current < time_max and len(slots) < 10:
            if (
                current.weekday() in self.working_days
                and self.working_hours_start <= current.time() < self.working_hours_end
            ):
                slot_end = current + timedelta(minutes=duration_minutes)
                # Ensure slot ends within working hours
                if slot_end.time() <= self.working_hours_end:
                    if not self._overlaps_busy(current, slot_end, busy):
                        slot = {
                            "start": current.isoformat(),
                            "end": slot_end.isoformat(),
                        }
                        if not self._in_excluded(slot, exclude_slots or []):
                            slots.append(slot)
            current += timedelta(minutes=30)

        print(f"[Calendar] Found {len(slots)} available slots for {email}")
        return slots

    # ─────────────────────────────────────────
    # Create a calendar event
    # ─────────────────────────────────────────
    def create_event(
        self,
        title: str,
        start: str,
        end: str,
        attendees: list[str],
        description: str = "",
        location: str = "",
        video_link: bool = True,
    ) -> dict:
        """Create a Google Calendar event and send invites to attendees."""
        service = self._get_service(attendees[0])  # Use organizer's account

        event_body = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start if "Z" in start or "+" in start else start + ":00", "timeZone": "UTC"},
            "end": {"dateTime": end if "Z" in end or "+" in end else end + ":00", "timeZone": "UTC"},
            "attendees": [{"email": addr} for addr in attendees],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 30},
                ],
            },
            "sendUpdates": "all",  # Send invites automatically
        }

        if video_link:
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"sched_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        try:
            event = service.events().insert(
                calendarId="primary",
                body=event_body,
                conferenceDataVersion=1 if video_link else 0,
            ).execute()
            print(f"[Calendar] ✅ Event created: {event.get('id')} — {title}")
            return {
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "meet_link": event.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri"),
            }
        except Exception as e:
            print(f"[Calendar] ❌ Failed to create event: {e}")
            return {"error": str(e)}

    def delete_event(self, organizer_email: str, event_id: str) -> bool:
        """Delete/cancel an event (used on reschedule or cancellation)."""
        try:
            service = self._get_service(organizer_email)
            service.events().delete(
                calendarId="primary",
                eventId=event_id,
                sendUpdates="all",
            ).execute()
            return True
        except Exception as e:
            print(f"[Calendar] delete_event failed: {e}")
            return False

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────
    def _parse_dt(self, dt_str: str) -> datetime:
        dt_str = dt_str.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(dt_str).replace(tzinfo=None)
        except ValueError:
            return datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S")

    def _overlaps_busy(self, start: datetime, end: datetime, busy: list) -> bool:
        for b_start, b_end in busy:
            if start < b_end and end > b_start:
                return True
        return False

    def _in_excluded(self, slot: dict, excluded: list) -> bool:
        return any(s.get("start") == slot["start"] for s in excluded)


# ─────────────────────────────────────────
# Mock for testing without Google credentials
# ─────────────────────────────────────────

class MockCalendarService:
    """Simulates Google Calendar responses for local testing."""

    def freebusy(self):
        return self

    def query(self, body):
        return self

    def execute(self):
        # Simulate some busy periods
        now = datetime.utcnow()
        return {
            "calendars": {
                "mock@example.com": {
                    "busy": [
                        {
                            "start": (now + timedelta(hours=3)).isoformat() + "Z",
                            "end": (now + timedelta(hours=4)).isoformat() + "Z",
                        }
                    ]
                }
            }
        }

    def events(self):
        return self

    def insert(self, **kwargs):
        return self

    def delete(self, **kwargs):
        return self


class MockCalendarClient(CalendarClient):
    """Drop-in replacement for testing without Google credentials."""

    def __init__(self):
        self.working_hours_start = time(9, 0)
        self.working_hours_end = time(18, 0)
        self.working_days = {0, 1, 2, 3, 4}

    def get_available_slots(self, email, duration_minutes=60, days_ahead=14, exclude_slots=None):
        """Return mock slots for testing."""
        slots = []
        now = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
        for day_offset in range(1, 5):
            base = now + timedelta(days=day_offset)
            if base.weekday() < 5:  # Weekday
                slots.append({
                    "start": base.replace(hour=10).isoformat(),
                    "end": (base.replace(hour=10) + timedelta(minutes=duration_minutes)).isoformat(),
                })
                slots.append({
                    "start": base.replace(hour=14).isoformat(),
                    "end": (base.replace(hour=14) + timedelta(minutes=duration_minutes)).isoformat(),
                })
        return slots[:6]

    def create_event(self, title, start, end, attendees, **kwargs):
        event_id = f"mock_event_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"[MockCalendar] Created event '{title}' from {start} to {end} for {attendees}")
        return {
            "event_id": event_id,
            "html_link": f"https://calendar.google.com/calendar/event?eid={event_id}",
            "meet_link": "https://meet.google.com/mock-meeting-link",
        }

    def delete_event(self, organizer_email, event_id):
        print(f"[MockCalendar] Deleted event {event_id}")
        return True
