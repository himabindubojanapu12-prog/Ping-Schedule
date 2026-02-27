"""
Interview Scheduling Agent
Orchestrates email parsing, availability detection, and calendar booking.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field


def process_candidate_input(self, request_id, candidate_input):

    request = self.active_requests.get(request_id)

    if not request:
        return "❌ Invalid request ID"

    candidate_input = candidate_input.strip().lower()

    # SCENARIO 1: Cancel
    if candidate_input == "cancel":
        request.status = "cancelled"
        return "🚫 Interview Cancelled"

    # SCENARIO 2: Reschedule
    if candidate_input == "reschedule":
        return f"📅 Available slots again:\n{request.proposed_slots}"

    # SCENARIO 3: Slot selection
    for slot in request.proposed_slots:
        if candidate_input in slot.lower():
            self.calendar_client.book_slot(slot)
            request.confirmed_slot = slot
            request.status = "confirmed"
            return f"✅ Interview Confirmed for {slot}"

    # SCENARIO 4: Invalid reply
    return "⚠️ Invalid response. Please choose a valid slot or type 'cancel'."

@dataclass
class InterviewRequest:
    recruiter_email: str
    candidate_email: str
    job_title: str
    duration_minutes: int = 60
    conversation_history: list = field(default_factory=list)
    recruiter_slots: list = field(default_factory=list)
    candidate_slots: list = field(default_factory=list)
    confirmed_slot: Optional[dict] = None
    status: str = "pending"  # pending | awaiting_candidate | confirmed | cancelled


class SchedulerAgent:
    """
    Core agent that negotiates interview times via email.
    Uses an LLM for natural language understanding of availability.
    """

    def __init__(self, llm_client, email_client, calendar_client):
        self.llm = llm_client
        self.email = email_client
        self.calendar = calendar_client
        self.active_requests: dict[str, InterviewRequest] = {}

    # ─────────────────────────────────────────
    # Entry point: Recruiter kicks off scheduling
    # ─────────────────────────────────────────
    def initiate_scheduling(
        self,
        recruiter_email: str,
        candidate_email: str,
        job_title: str,
        duration_minutes: int = 60,
    ) -> InterviewRequest:
        request = InterviewRequest(
            recruiter_email=recruiter_email,
            candidate_email=candidate_email,
            job_title=job_title,
            duration_minutes=duration_minutes,
        )
        request_id = f"req_{datetime.now().strftime('%Y%m%d%H%M%S')}_{candidate_email.split('@')[0]}"
        self.active_requests[request_id] = request

        # Step 1: Check recruiter's calendar for open slots
        recruiter_slots = self.calendar.get_available_slots(
            email=recruiter_email,
            duration_minutes=duration_minutes,
            days_ahead=14,
        )
        request.recruiter_slots = recruiter_slots

        # Step 2: Email candidate with available times
        self._send_availability_request(request_id, request, recruiter_slots)
        request.status = "awaiting_candidate"

        print(f"[Agent] Scheduling initiated for {candidate_email} | Request: {request_id}")
        return request_id, request

    # ─────────────────────────────────────────
    # Handle incoming email reply
    # ─────────────────────────────────────────
    def handle_email_reply(self, request_id: str, sender: str, email_body: str) -> dict:
        if request_id not in self.active_requests:
            return {"status": "error", "message": "Unknown request ID"}

        request = self.active_requests[request_id]
        request.conversation_history.append({"from": sender, "body": email_body})

        print(f"[Agent] Processing reply from {sender} for request {request_id}")

        # Use LLM to extract availability from natural language
        extracted = self._extract_availability_with_llm(email_body, request)
        print(f"[Agent] LLM extracted action: {extracted.get('action')} | slots: {extracted.get('slots')}")

        if extracted["action"] == "provide_availability":
            return self._process_candidate_availability(request_id, request, extracted["slots"])

        elif extracted["action"] == "confirm":
            return self._confirm_booking(request_id, request)

        elif extracted["action"] == "decline":
            request.status = "cancelled"
            self._send_cancellation_notice(request)
            return {"status": "cancelled"}

        elif extracted["action"] == "request_other_times":
            return self._handle_no_overlap(request_id, request)

        else:
            # For unclear responses, still try to process as availability
            if extracted.get("slots"):
                return self._process_candidate_availability(request_id, request, extracted["slots"])
            return {"status": "awaiting_response"}

    # ─────────────────────────────────────────
    # LLM: Parse availability from email text
    # ─────────────────────────────────────────
    def _extract_availability_with_llm(self, email_body: str, request: InterviewRequest) -> dict:
        # Format recruiter slots in human-readable form so LLM can match against them
        recruiter_slots_display = ""
        if request.recruiter_slots:
            lines = []
            for s in request.recruiter_slots:
                try:
                    dt = self._parse_dt(s["start"])
                    lines.append(f"  - {dt.strftime('%A, %B %d, %Y at %I:%M %p')} | raw: {s['start']}")
                except Exception:
                    lines.append(f"  - {s['start']}")
            recruiter_slots_display = "Recruiter's available slots that were offered to candidate:\n" + "\n".join(lines)

        prompt = f"""You are an assistant that extracts scheduling information from emails.

Today's date: {datetime.now().strftime('%A, %B %d, %Y')}

{recruiter_slots_display}

Candidate's email reply:
\"\"\"
{email_body}
\"\"\"

The candidate was previously sent the recruiter's available slots listed above.
Now they are replying to say which time works for them.

Your job: Figure out which of the recruiter's slots the candidate is referring to and return it.

Return a JSON object:
{{
  "action": "provide_availability" | "confirm" | "decline" | "request_other_times" | "unclear",
  "slots": [
    {{
      "date": "YYYY-MM-DD",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "timezone": null
    }}
  ],
  "message": "any message to pass along"
}}

STRICT rules:
- If candidate says "Monday works" or "Monday at 10am" → find the matching Monday slot from the recruiter's list above and return that exact date in YYYY-MM-DD format
- If candidate confirms any specific slot → action = "provide_availability" with that slot's exact date and time
- If end_time not mentioned → add {request.duration_minutes} minutes to start_time
- If candidate says they can't make it or wants to withdraw → action = "decline"
- If candidate asks for different times → action = "request_other_times"
- ALWAYS return the exact YYYY-MM-DD date from the recruiter slots list above, never a vague date
- Only return valid JSON, no other text."""

        response = self.llm.complete(prompt)
        try:
            # Clean up markdown code blocks if LLM returns them
            clean = response.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except Exception:
                    pass
            print(f"[Agent] ⚠️ LLM response could not be parsed: {response[:200]}")
            return {"action": "unclear", "slots": [], "message": response}

    # ─────────────────────────────────────────
    # Find overlapping slots between parties
    # ─────────────────────────────────────────
    def _process_candidate_availability(
        self, request_id: str, request: InterviewRequest, candidate_slots: list
    ) -> dict:
        request.candidate_slots = candidate_slots

        if not candidate_slots:
            print("[Agent] ⚠️ No candidate slots extracted — sending retry email")
            return self._handle_no_overlap(request_id, request)

        overlap = self._find_overlap(request.recruiter_slots, candidate_slots, request.duration_minutes)
        print(f"[Agent] Overlap check: {len(request.recruiter_slots)} recruiter slots vs {len(candidate_slots)} candidate slots → {len(overlap)} overlaps")

        if overlap:
            best_slot = overlap[0]
            request.confirmed_slot = best_slot

            # Book the calendar event
            event = self.calendar.create_event(
                title=f"Interview: {request.job_title}",
                start=best_slot["start"],
                end=best_slot["end"],
                attendees=[request.recruiter_email, request.candidate_email],
                description=f"Interview for {request.job_title} position.\nScheduled by Interview Scheduling Agent.",
            )

            request.status = "confirmed"

            # Send confirmation emails to BOTH parties
            self._send_confirmation(request, best_slot, event)

            print(f"[Agent] ✅ Booked: {best_slot['start']} for {request.candidate_email}")
            return {"status": "confirmed", "slot": best_slot, "calendar_event": event}

        else:
            print("[Agent] No overlap found — trying alternative slots")
            return self._handle_no_overlap(request_id, request)

    def _find_overlap(
        self, recruiter_slots: list, candidate_slots: list, duration_minutes: int
    ) -> list:
        """
        Return list of slots that work for both parties.
        Matches by exact date+hour first, then by day-of-week as fallback.
        """
        overlapping = []

        for rs in recruiter_slots:
            try:
                rs_start = self._parse_dt(rs["start"])
                rs_end = self._parse_dt(rs["end"])
            except Exception as e:
                print(f"[Agent] Could not parse recruiter slot {rs}: {e}")
                continue

            for cs in candidate_slots:
                try:
                    cs_start = self._parse_candidate_slot_start(cs)
                    cs_end = self._parse_candidate_slot_end(cs, duration_minutes)
                except Exception as e:
                    print(f"[Agent] Could not parse candidate slot {cs}: {e}")
                    continue

                matched = False

                # Match 1: exact date + hour
                if rs_start.date() == cs_start.date() and rs_start.hour == cs_start.hour:
                    matched = True
                    print(f"[Agent] ✓ Exact match: {rs_start.date()} {rs_start.hour}:00")

                # Match 2: same day-of-week + same hour (handles date resolution mismatch)
                elif rs_start.weekday() == cs_start.weekday() and rs_start.hour == cs_start.hour:
                    matched = True
                    print(f"[Agent] ✓ Day-of-week match: {rs_start.strftime('%A')} {rs_start.hour}:00")

                # Match 3: candidate only said day name with no time → match any slot on that day
                elif rs_start.date() == cs_start.date() and cs_start.hour == 0:
                    matched = True
                    print(f"[Agent] ✓ Date-only match: {rs_start.date()}")

                # Match 4: full time range overlap
                else:
                    overlap_start = max(rs_start, cs_start)
                    overlap_end = min(rs_end, cs_end)
                    if (overlap_end - overlap_start) >= timedelta(minutes=duration_minutes):
                        matched = True
                        print(f"[Agent] ✓ Range overlap match")

                if matched:
                    overlapping.append({
                        "start": rs_start.isoformat(),
                        "end": rs_end.isoformat(),
                        "display": rs_start.strftime("%A, %B %d at %I:%M %p"),
                    })

        # Remove duplicates
        seen = set()
        unique = []
        for s in overlapping:
            if s["start"] not in seen:
                seen.add(s["start"])
                unique.append(s)

        return unique

    def _parse_candidate_slot_start(self, cs: dict) -> datetime:
        """Parse a candidate slot dict into a start datetime."""
        date_str = cs.get("date", "")
        time_str = cs.get("start_time", "00:00")

        if not date_str:
            raise ValueError(f"No date in candidate slot: {cs}")

        # Handle both "HH:MM" and "HH:MM:SS"
        time_str = time_str[:5]  # take only HH:MM
        return datetime.strptime(f"{date_str}T{time_str}", "%Y-%m-%dT%H:%M")

    def _parse_candidate_slot_end(self, cs: dict, duration_minutes: int) -> datetime:
        """Parse end time or derive from start + duration."""
        start = self._parse_candidate_slot_start(cs)
        end_time_str = cs.get("end_time", "")

        if end_time_str:
            try:
                end_time_str = end_time_str[:5]
                end = datetime.strptime(f"{cs['date']}T{end_time_str}", "%Y-%m-%dT%H:%M")
                if end > start:
                    return end
            except Exception:
                pass

        return start + timedelta(minutes=duration_minutes)

    def _parse_dt(self, dt_str: str) -> datetime:
        """Parse various datetime string formats."""
        # Remove timezone info for naive comparison
        dt_str = re.sub(r'[+-]\d{2}:\d{2}$', '', dt_str.strip())
        dt_str = dt_str.replace("Z", "")

        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse datetime: {dt_str}")

    # ─────────────────────────────────────────
    # Handle no overlap — fetch more recruiter slots
    # ─────────────────────────────────────────
    def _handle_no_overlap(self, request_id: str, request: InterviewRequest) -> dict:
        new_slots = self.calendar.get_available_slots(
            email=request.recruiter_email,
            duration_minutes=request.duration_minutes,
            days_ahead=21,
            exclude_slots=request.recruiter_slots,
        )
        if new_slots:
            request.recruiter_slots.extend(new_slots)
            self._send_availability_request(request_id, request, new_slots, retry=True)
            return {"status": "awaiting_candidate", "message": "Sent alternative times"}
        else:
            request.status = "needs_human"
            self._escalate_to_recruiter(request)
            return {"status": "escalated", "message": "No available slots found — escalated to recruiter"}

    def _confirm_booking(self, request_id: str, request: InterviewRequest) -> dict:
        """Called when candidate confirms a previously offered slot."""
        if request.confirmed_slot:
            event = self.calendar.create_event(
                title=f"Interview: {request.job_title}",
                start=request.confirmed_slot["start"],
                end=request.confirmed_slot["end"],
                attendees=[request.recruiter_email, request.candidate_email],
            )
            request.status = "confirmed"
            self._send_confirmation(request, request.confirmed_slot, event)
            return {"status": "confirmed", "slot": request.confirmed_slot}
        return {"status": "error", "message": "No slot to confirm"}

    # ─────────────────────────────────────────
    # Email helpers
    # ─────────────────────────────────────────
    def _send_availability_request(
        self, request_id: str, request: InterviewRequest, slots: list, retry: bool = False
    ):
        # Format slots in human-readable way
        slot_lines = []
        for s in slots[:6]:
            try:
                dt = self._parse_dt(s["start"])
                slot_lines.append(f"  • {dt.strftime('%A, %B %d at %I:%M %p')} ({request.duration_minutes} mins)")
            except Exception:
                slot_lines.append(f"  • {s['start']} – {s['end']}")

        subject = f"Interview Scheduling – {request.job_title}"
        body = f"""Hi,

{"Thank you for your response! Unfortunately those times don't work. Here are some additional options:" if retry else f"We'd love to schedule your interview for the {request.job_title} position."}

Please reply with which time works best for you, or suggest an alternative:

{chr(10).join(slot_lines)}

Simply reply to this email with your preferred time — our scheduling assistant will take care of the rest!

Best regards,
Interview Scheduling Assistant

──────────────────────────────
[Request ID: {request_id}]
──────────────────────────────"""

        self.email.send(
            to=request.candidate_email,
            subject=subject,
            body=body,
        )

    def _send_confirmation(self, request: InterviewRequest, slot: dict, event: dict = None):
        """Send confirmation emails to BOTH candidate and recruiter."""

        # Format the slot nicely
        try:
            dt_start = self._parse_dt(slot["start"])
            dt_end = self._parse_dt(slot["end"])
            slot_display = dt_start.strftime("%A, %B %d, %Y at %I:%M %p")
            duration_display = f"{request.duration_minutes} minutes"
        except Exception:
            slot_display = slot.get("display", slot["start"])
            duration_display = f"{request.duration_minutes} minutes"

        meet_link = ""
        if event and event.get("meet_link"):
            meet_link = f"\nGoogle Meet Link: {event['meet_link']}"

        # ── Email to CANDIDATE ──
        candidate_body = f"""Hi,

Great news! Your interview has been successfully scheduled. 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INTERVIEW CONFIRMED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Role     : {request.job_title}
  Date     : {slot_display}
  Duration : {duration_display}{meet_link}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A calendar invite has been sent to your email. Please accept it to confirm attendance.

Tips for your interview:
  • Join 5 minutes early
  • Test your audio/video beforehand
  • Have your resume handy

Best of luck! We look forward to speaking with you.

Best regards,
Interview Scheduling Assistant"""

        self.email.send(
            to=request.candidate_email,
            subject=f"✅ Interview Confirmed – {request.job_title}",
            body=candidate_body,
        )

        # ── Email to RECRUITER ──
        recruiter_body = f"""Hi,

The interview has been successfully scheduled with the candidate.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INTERVIEW BOOKED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Role      : {request.job_title}
  Candidate : {request.candidate_email}
  Date      : {slot_display}
  Duration  : {duration_display}{meet_link}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A calendar invite has been added to your calendar automatically.

Best regards,
Interview Scheduling Assistant"""

        self.email.send(
            to=request.recruiter_email,
            subject=f"✅ Interview Booked – {request.job_title} | {slot_display}",
            body=recruiter_body,
        )

        print(f"[Agent] 📧 Confirmation emails sent to {request.candidate_email} and {request.recruiter_email}")

    def _send_cancellation_notice(self, request: InterviewRequest):
        self.email.send(
            to=request.recruiter_email,
            subject=f"Interview Declined – {request.job_title}",
            body=f"""Hi,

The candidate has declined the interview request.

  Candidate : {request.candidate_email}
  Position  : {request.job_title}

Please reach out directly if you'd like to follow up.

Best regards,
Interview Scheduling Assistant""",
        )

    def _escalate_to_recruiter(self, request: InterviewRequest):
        self.email.send(
            to=request.recruiter_email,
            subject=f"⚠️ Manual Scheduling Required – {request.job_title}",
            body=f"""Hi,

The automated scheduling agent was unable to find a mutually available time.

  Candidate : {request.candidate_email}
  Position  : {request.job_title}

Please reach out to the candidate directly to schedule the interview.

Best regards,
Interview Scheduling Assistant""",
        )