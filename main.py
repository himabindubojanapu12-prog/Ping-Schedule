"""
Interview Scheduling Agent — Demo Runner
Demonstrates the full scheduling workflow with mock components.

Run: python main.py
"""



""
import time
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scheduler_agent import SchedulerAgent
from calendar_client import MockCalendarClient
from email_client import EmailClient  
from llm_client import LLMClient




# ─────────────────────────────────────────
# Fake Email dataclass (shared by both clients)
# ─────────────────────────────────────────

@dataclass
class FakeEmail:
    sender: str
    subject: str
    body: str
    request_id: Optional[str]
    received_at: datetime


# ─────────────────────────────────────────
# Mock Email Client for Demo
# ─────────────────────────────────────────

class MockEmailClient:
    """Simulates email sending/receiving for demo purposes."""

    def __init__(self):
        self.sent_emails = []
        self.pending_replies = []

    def send(self, to: str, subject: str, body: str, reply_to: str = None):
        email_record = {
            "to": to,
            "subject": subject,
            "body": body,
            "reply_to": reply_to,
            "sent_at": datetime.now().isoformat(),
        }
        self.sent_emails.append(email_record)
        print(f"\n{'='*60}")
        print(f"📧 EMAIL SENT")
        print(f"   To:      {to}")
        print(f"   Subject: {subject}")
        print(f"   Body:\n{self._indent(body)}")
        print(f"{'='*60}")

    def fetch_new_replies(self):
        """Return and clear pending simulated replies."""
        replies = self.pending_replies.copy()
        self.pending_replies.clear()
        return replies

    def simulate_reply(self, sender: str, body: str, request_id: str):
        """Inject a simulated reply for testing."""
        self.pending_replies.append(FakeEmail(
            sender=sender,
            subject="Re: Interview Scheduling",
            body=body + f"\n\n[Request ID: {request_id}]",
            request_id=request_id,
            received_at=datetime.now(),
        ))
        preview = body[:80] + "..." if len(body) > 80 else body
        print(f"\n📨 SIMULATED REPLY from {sender}: \"{preview}\"")

    def _indent(self, text: str, indent: str = "   ") -> str:
        return "\n".join(indent + line for line in text.split("\n"))


# ─────────────────────────────────────────
# Real Email Client Wrapper
# Adds simulate_reply support on top of the real EmailClient
# ─────────────────────────────────────────

class RealEmailClientWithSimulate:
    """
    Wraps the real EmailClient and adds a simulate_reply() method
    so demo scenarios work even when using live Gmail credentials.
    """

    def __init__(self, real_client):
        self._real = real_client
        self.sent_emails = []
        self.pending_replies = []   # holds injected FakeEmail objects

    def send(self, to: str, subject: str, body: str, reply_to: str = None):
        """Delegates to real client for actual sending."""
        result = self._real.send(to=to, subject=subject, body=body, reply_to=reply_to)
        self.sent_emails.append({"to": to, "subject": subject})
        print(f"\n{'='*60}")
        print(f"📧 REAL EMAIL SENT")
        print(f"   To:      {to}")
        print(f"   Subject: {subject}")
        print(f"{'='*60}")
        return result

    def fetch_new_replies(self):
        """
        Returns any simulated (injected) replies first.
        Then also checks real inbox via the underlying client (if supported).
        """
        replies = self.pending_replies.copy()
        self.pending_replies.clear()

        # Also fetch real replies if underlying client supports it
        if hasattr(self._real, "fetch_new_replies"):
            try:
                real_replies = self._real.fetch_new_replies()
                replies.extend(real_replies)
            except Exception as e:
                print(f"[EmailClient] fetch_new_replies error (non-fatal): {e}")

        return replies

    def simulate_reply(self, sender: str, body: str, request_id: str):
        """
        Injects a fake reply into the polling queue.
        This is what was MISSING — now it works with real EmailClient too.
        """
        self.pending_replies.append(FakeEmail(
            sender=sender,
            subject="Re: Interview Scheduling",
            body=body + f"\n\n[Request ID: {request_id}]",
            request_id=request_id,
            received_at=datetime.now(),
        ))
        preview = body[:80] + "..." if len(body) > 80 else body
        print(f"\n📨 SIMULATED REPLY from {sender}: \"{preview}\"")

    def __getattr__(self, name):
        """
        Fallback: any other method/attribute not defined above
        is forwarded to the real client transparently.
        """
        return getattr(self._real, name)


# ─────────────────────────────────────────
# Background Email Polling Loop
# ─────────────────────────────────────────

class EmailPollingService:
    """
    Polls for new email replies and routes them to the agent.
    In production: runs as a background thread or cron job.
    """

    def __init__(self, agent: SchedulerAgent, email_client, poll_interval: int = 30):
        self.agent = agent
        self.email = email_client
        self.poll_interval = poll_interval
        self._stop = threading.Event()

    def start(self):
        thread = threading.Thread(target=self._poll_loop, daemon=True)
        thread.start()
        print(f"[Poller] Started — polling every {self.poll_interval}s")
        return thread

    def stop(self):
        self._stop.set()

    def _poll_loop(self):
        while not self._stop.is_set():
            self._check_inbox()
            self._stop.wait(self.poll_interval)

    def _check_inbox(self):
        replies = self.email.fetch_new_replies()
        for reply in replies:
            if reply.request_id:
                print(f"\n[Poller] Routing reply from {reply.sender} → request {reply.request_id}")
                result = self.agent.handle_email_reply(
                    request_id=reply.request_id,
                    sender=reply.sender,
                    email_body=reply.body,
                )
                print(f"[Poller] Agent result: {result}")
            else:
                print(f"[Poller] ⚠️  No request ID from {reply.sender} — skipping")


# ─────────────────────────────────────────
# Demo Scenarios
# ─────────────────────────────────────────

def run_demo():
    print("\n" + "🤖 " * 20)
    print("   INTERVIEW SCHEDULING AGENT — DEMO")
    print("🤖 " * 20 + "\n")

    # ── Initialize real email client and WRAP it ──
    from email_client import EmailClient, gmail_config

    raw_email_client = EmailClient(gmail_config(
        username="dedeepyabitra6@gmail.com",
        app_password="nwzh evit gcry fafm"
    ))

    # THIS is the fix — wrap it so simulate_reply() works
    email_client = RealEmailClientWithSimulate(raw_email_client)

    calendar_client = MockCalendarClient()
    llm_client = LLMClient()

    agent = SchedulerAgent(
        llm_client=llm_client,
        email_client=email_client,
        calendar_client=calendar_client,
    )

    # Start background poller
    poller = EmailPollingService(agent, email_client, poll_interval=2)
    poller.start()

    # ── SCENARIO 1: Successful scheduling ──
    print("\n" + "─" * 60)
    print("SCENARIO 1: Successful interview scheduling")
    print("─" * 60)

    request_id, request = agent.initiate_scheduling(
        recruiter_email="dedeepyabitra6@gmail.com",
        candidate_email="vepadanandini123@gmail.com",
        job_title="Senior Software Engineer",
        duration_minutes=60,
    )

    time.sleep(0.5)

    # Simulate candidate replying with availability
    email_client.simulate_reply(
        sender="vepadanandini123@gmail.com",
        body="I'm available Monday at 10am or Tuesday at 2pm next week.",
        request_id=request_id,
    )

    time.sleep(3)  # Let poller process

    print(f"\n[Demo] Scenario 1 status: {agent.active_requests[request_id].status}")

    # ── SCENARIO 2: No overlap, retry ──
    print("\n" + "─" * 60)
    print("SCENARIO 2: No overlap — agent finds alternative slots")
    print("─" * 60)

    request_id2, request2 = agent.initiate_scheduling(
        recruiter_email="dedeepyabitra6@gmail.com",
        candidate_email="vepadanandini123@gmail.com",
        job_title="Product Manager",
        duration_minutes=45,
    )

    time.sleep(0.5)

    # Candidate offers times that don't overlap with recruiter's mock slots
    email_client.simulate_reply(
        sender="vepadanandini123@gmail.com",
        body="I'm only free Saturday morning or Sunday afternoon this week.",
        request_id=request_id2,
    )

    time.sleep(3)

    print(f"\n[Demo] Scenario 2 status: {agent.active_requests[request_id2].status}")

    # ── SCENARIO 3: Candidate declines ──
    print("\n" + "─" * 60)
    print("SCENARIO 3: Candidate declines interview")
    print("─" * 60)

    request_id3, request3 = agent.initiate_scheduling(
        recruiter_email="dedeepyabitra6@gmail.com",
        candidate_email="himabindubojanapu12@gmail.com",   # fixed typo: .co → .com
        job_title="Data Scientist",
        duration_minutes=60,
    )

    time.sleep(0.5)

    email_client.simulate_reply(
        sender="himabindubojanapu12@gmail.com",
        body="Thank you for the opportunity, but I would like to withdraw my application.",
        request_id=request_id3,
    )

    time.sleep(3)

    print(f"\n[Demo] Scenario 3 status: {agent.active_requests[request_id3].status}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    for rid, req in agent.active_requests.items():
        print(f"  {rid[:30]:<30} | {req.job_title:<30} | Status: {req.status}")

    print(f"\n  Total emails sent: {len(email_client.sent_emails)}")

    poller.stop()
    print("\n✅ Demo complete.\n")


if __name__ == "__main__":
    run_demo() 
    
    