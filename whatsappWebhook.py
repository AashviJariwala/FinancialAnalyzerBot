"""Persistent Twilio WhatsApp portfolio bot backed by PostgreSQL."""
from itsdangerous import exc
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from flask import Response, request, session
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

WEBHOOK_PATH = "/whatsapp/webhook"
WHATSAPP_NUMBER = re.compile(r"whatsapp:(\+[1-9][0-9]{1,14})")
ASK_NAME = ("👋 Welcome to your Personal Investment Suite!\n"
            "Please enter the client name exactly as it appears on the website.")
UNAVAILABLE = "I couldn't answer that question. Please try again."
LOADING_PORTFOLIO = "⏳ Loading your portfolio… Please wait."
THINKING_MESSAGE = "🤔 Thinking… Preparing your answer, please wait."
LEASE_MINUTES = 15
MAX_HISTORY = 30

MENU_SECTIONS = (
    ("📂 Portfolio Overview", (
        (1, "Portfolio Summary", "Summarize the amount invested, current value, gains, and annual return (XIRR)."),
        (2, "Detailed Holdings", "List the schemes and summarize nominee information where available."),
        (3, "Family Breakdown", "Show the portfolio allocation across family holders."),
    )),
    ("📈 Performance & Projections", (
        (4, "Annual Return (XIRR)", "What is the portfolio's annual return (XIRR)?"),
        (5, "Best-performing Scheme", "Which scheme is performing best? State the metric used."),
        (6, "Highest Unrealised Gain", "Which fund has the highest unrealised gain?"),
        (7, "Equity Funds", "List all equity funds in the portfolio."),
        (8, "Negative Returns", "Which funds are giving negative returns?"),
    )),
    ("📅 SIPs & Bank Details", (
        (9, "Monthly SIP Amount", "What is the total monthly SIP amount?"),
        (10, "Upcoming SIP Dates", "List upcoming SIP dates shown in the portfolio data."),
        (11, "Registered Bank Details", "Show registered bank names and any already-masked account identifiers available. Omit full account numbers."),
        (12, "Active SIPs", "Show all active SIPs."),
        (13, "Paused or Stopped SIPs", "Which SIPs are currently paused or stopped?"),
    )),
    ("💬 Advice & Recommendations", (
        (14, "Portfolio Improvements", "Suggest portfolio improvements based on the available data."),
        (15, "Diversification", "Is the portfolio well diversified?"),
        (16, "Increasing SIPs", "What should I consider before increasing my SIP amount based on current performance?"),
        (17, "Portfolio Risk", "What is the risk profile of the portfolio based on the available data?"),
    )),
)
MENU_QUESTIONS = {str(n): q for _, items in MENU_SECTIONS for n, _, q in items}


def _menu(client_name):
    name = " ".join(client_name.split())[:100].translate(str.maketrans("", "", "*_~`"))
    lines = [f"👋 *Hello {name}!* Welcome to your Personal Investment Suite.",
             "", "Reply with an option number or ask a question in your own words."]
    for heading, options in MENU_SECTIONS:
        lines.extend(("", f"*{heading}*"))
        lines.extend(f"{n}. {label}" for n, label, _ in options)
    lines.extend(("", "💡 Type *menu* to see these options or *reset* to enter another client name."))
    return "\n".join(lines)


def _reply(message=None):
    response = MessagingResponse()
    if message:
        response.message(message)
    return Response(str(response), mimetype="application/xml")


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _initialize_database():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_conversations (
                sender TEXT PRIMARY KEY,
                client_name TEXT,
                file_path TEXT,
                state TEXT NOT NULL DEFAULT 'WAITING_FOR_NAME',
                chat_history JSONB NOT NULL DEFAULT '[]'::jsonb,
                task_token UUID,
                lease_until TIMESTAMPTZ,
                last_message_sid TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


def register_whatsapp_webhook(app, download_portfolio, load_analyzer):
    """Register after app.py has defined /chat."""
    chat_view = app.view_functions["chat"]
    executor = ThreadPoolExecutor(max_workers=2)
    _initialize_database()

    def send(twilio, sender, recipient, message):
        MAX_LENGTH = 1500
        HEADER_RESERVE = 40
        CHUNK_LENGTH = MAX_LENGTH - HEADER_RESERVE

        try:
            if not message:
                return

            parts = []
            remaining = message

            # Divide the complete GroqCloud response
            while remaining:
                if len(remaining) <= CHUNK_LENGTH:
                    parts.append(remaining)
                    break

                # First preference: paragraph boundary
                split_at = remaining.rfind(
                    "\n\n", 0, CHUNK_LENGTH + 1
                )

                # Second preference: newline
                if split_at < CHUNK_LENGTH // 2:
                    split_at = remaining.rfind(
                        "\n", 0, CHUNK_LENGTH + 1
                    )

                # Third preference: sentence boundary
                if split_at < CHUNK_LENGTH // 2:
                    split_at = remaining.rfind(
                        ". ", 0, CHUNK_LENGTH + 1
                    )
                    if split_at >= 0:
                        split_at += 1

                # Fourth preference: word boundary
                if split_at < CHUNK_LENGTH // 2:
                    split_at = remaining.rfind(
                        " ", 0, CHUNK_LENGTH + 1
                    )

                # Last resort: character boundary
                if split_at <= 0:
                    split_at = CHUNK_LENGTH

                # Preserve every character, including spaces/newlines
                parts.append(remaining[:split_at])
                remaining = remaining[split_at:]

            total_parts = len(parts)

            app.logger.info(
                "Sending WhatsApp response: %s characters, %s parts",
                len(message),
                total_parts
            )

            # Send each part in order
            for index, part in enumerate(parts, start=1):

                if total_parts > 1:
                    body = (
                        f"*Part {index}/{total_parts}*\n\n"
                        f"{part}"
                    )
                else:
                    body = part

                twilio.messages.create(
                    from_=recipient,
                    to=sender,
                    body=body
                )

                app.logger.info(
                    "WhatsApp part %s/%s submitted: %s characters",
                    index,
                    total_parts,
                    len(body)
                )
        except Exception:
            app.logger.exception(
                "Failed to send WhatsApp reply"
            )




    def finish(sender, token, client_name, file_path, question, answer, loading):
        """Update only if this worker still owns the task (reset-safe)."""
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT chat_history FROM whatsapp_conversations
                    WHERE sender=%s AND task_token=%s FOR UPDATE
                """, (sender, token))
                row = cur.fetchone()
                if row is None:
                    return False
                history = row[0] or []
                if not loading and answer:
                    history = (history + [
                        {"role": "user", "text": question},
                        {"role": "bot", "text": answer},
                    ])[-MAX_HISTORY:]
                cur.execute("""
                    UPDATE whatsapp_conversations
                    SET client_name=%s, file_path=%s, state=%s,
                        chat_history=%s, task_token=NULL, lease_until=NULL,
                        updated_at=NOW()
                    WHERE sender=%s AND task_token=%s
                """, (client_name, file_path,
                      "READY" if client_name else "WAITING_FOR_NAME",
                      Jsonb(history), sender, token))
                return True

    def run_task(sender, recipient, token, text, loading, client_name, file_path,
                 history, twilio):
        answer = None
        try:
            if loading:
                downloaded = download_portfolio(text)
                if load_analyzer(downloaded) is None:
                    raise ValueError("Could not parse downloaded portfolio")
                file_path = str(Path(downloaded).resolve())
                client_name = text
                message = _menu(client_name)
            else:
                # The durable client name allows automatic recovery of missing files.
                if not file_path or not Path(file_path).is_file():
                    downloaded = download_portfolio(client_name)
                    if load_analyzer(downloaded) is None:
                        raise ValueError("Could not parse refreshed portfolio")
                    file_path = str(Path(downloaded).resolve())
                with app.test_request_context(
                    "/chat", method="POST", json={"message": text}
                ):
                    session["file_path"] = file_path
                    session["client_name"] = client_name
                    session["chat_history"] = history
                    result = app.make_response(chat_view()).get_json()
                answer = result.get("answer") if result and result.get("success") else None
                if not isinstance(answer, str) or answer.startswith("Error contacting GroqCloud"):
                    raise ValueError("Chat service returned no valid answer")
                message = answer.strip() or UNAVAILABLE
            committed = finish(sender, token, client_name, file_path, text,
                               answer, loading)
        except Exception:
            app.logger.exception("WhatsApp task failed")
            try:
                committed = finish(sender, token,
                                   None if loading else client_name,
                                   None if loading else file_path,
                                   text, None, loading)
            except Exception:
                app.logger.exception("Could not release WhatsApp task")
                return
            message = ("I couldn't load that portfolio. Please enter the client name again."
                       if loading else UNAVAILABLE + " Your selected client is still saved.")
        if committed:
            send(twilio, sender, recipient, message)

    @app.post(WEBHOOK_PATH)
    def whatsapp_webhook():
        public_url = os.getenv("TWILIO_WHATSAPP_WEBHOOK_URL", "").strip()
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        allowed_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "").strip()
        if not all((public_url, auth_token, account_sid, allowed_number)):
            return Response(status=503)
        signature = request.headers.get("X-Twilio-Signature", "")
        if request.query_string or not signature or not RequestValidator(auth_token).validate(
            public_url, request.form, signature
        ):
            return Response(status=403)
        if request.form.get("AccountSid") != account_sid:
            return Response(status=403)

        sender = request.form.get("From", "")
        recipient = request.form.get("To", "")
        sid = request.form.get("MessageSid", "")
        number = WHATSAPP_NUMBER.fullmatch(sender)
        if not number or not WHATSAPP_NUMBER.fullmatch(recipient) or not sid:
            return Response(status=400)
        # This is the authorized user's phone number, NOT the Twilio sandbox number.
        if number.group(1) != allowed_number:
            return _reply("This WhatsApp number isn't enabled for portfolio access.")

        text = request.form.get("Body", "").strip()
        command = text.casefold()
        token = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO whatsapp_conversations (sender)
                        VALUES (%s) ON CONFLICT (sender) DO NOTHING
                    """, (sender,))
                    cur.execute("""
                        SELECT client_name, file_path, state, chat_history,
                               task_token, lease_until, last_message_sid
                        FROM whatsapp_conversations WHERE sender=%s FOR UPDATE
                    """, (sender,))
                    client_name, file_path, state, history, old_token, lease, last_sid = cur.fetchone()
                    if sid == last_sid:
                        return _reply()
                    cur.execute("""
                        UPDATE whatsapp_conversations
                        SET last_message_sid=%s WHERE sender=%s
                    """, (sid, sender))

                    if command in {"reset", "change"}:
                        # Preserve only sender and deduplication SID.
                        # In-flight workers cannot restore old state afterward.
                        cur.execute("""
                            UPDATE whatsapp_conversations
                            SET client_name=NULL, file_path=NULL,
                                state='WAITING_FOR_NAME', chat_history='[]'::jsonb,
                                task_token=NULL, lease_until=NULL, updated_at=NOW()
                            WHERE sender=%s
                        """, (sender,))
                        return _reply(ASK_NAME)

                    if old_token and lease and lease > now:
                        return _reply("I'm still processing your previous message. Please wait.")
                    if not text:
                        return _reply(ASK_NAME if not client_name else "Please send a question as text.")
                    if command == "menu":
                        return _reply(_menu(client_name) if client_name else ASK_NAME)

                    loading = not bool(client_name)
                    if loading and last_sid is None:
                        # First message: introduce the bot before accepting a name.
                        return _reply(ASK_NAME)
                    if not loading and text.isdecimal():
                        question = MENU_QUESTIONS.get(text)
                        if question is None:
                            return _reply("Please choose a number from *menu*, or type your question.")
                        text = question
                    cur.execute("""
                        UPDATE whatsapp_conversations
                        SET state='PROCESSING', task_token=%s, lease_until=%s,
                            updated_at=NOW() WHERE sender=%s
                    """, (token, now + timedelta(minutes=LEASE_MINUTES), sender))
            # Transaction committed before the worker starts.
            try:
                executor.submit(run_task, sender, recipient, token, text, loading,
                                client_name, file_path, history or [],
                                Client(account_sid, auth_token))
            except Exception:
                app.logger.exception("Unable to schedule WhatsApp worker")
                finish(sender, token, client_name, file_path, text, None, loading)
                return _reply(UNAVAILABLE)
            return _reply(LOADING_PORTFOLIO if loading else THINKING_MESSAGE)
        except Exception:
            app.logger.exception("WhatsApp database/webhook failure")
            return Response("Temporary service issue", status=503)