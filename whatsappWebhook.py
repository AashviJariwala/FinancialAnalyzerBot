"""Load a portfolio by client name and answer questions over WhatsApp."""

import os
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from flask import Response, request, session
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

WEBHOOK_PATH = "/whatsapp/webhook"
WHATSAPP_NUMBER = re.compile(r"whatsapp:(\+[1-9][0-9]{1,14})")
ASK_NAME = """
👋Welcome to your Personal Investment Suite!
I am your dedicated digital financial companion. I can help you track your investments, view SIP details, monitor performance, and generate tax statements.

To personalize your experience, could you please tell me your name?
"""
UNAVAILABLE = "I couldn't answer that question. Please try again."


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
MENU_QUESTIONS = {
    str(number): question
    for _, options in MENU_SECTIONS
    for number, _, question in options
}


def _menu(client_name):
    name = " ".join(client_name.split())[:100].translate(str.maketrans("", "", "*_~`"))
    lines = [
        f"👋 *Hello {name}!* Welcome to your Personal Investment Suite.",
        "",
        "Reply with an option number (e.g. *1*) or ask a question in your own words.",
    ]
    for heading, options in MENU_SECTIONS:
        lines.extend(("", f"*{heading}*"))
        lines.extend(f"{number}. {label}" for number, label, _ in options)
    lines.extend(("", "💡 Type *menu* to see these options or *reset* to enter another client name."))
    return "\n".join(lines)


@dataclass
class Conversation:
    file_path: str | None = None
    busy: bool = False
    client_name: str | None = None


def _reply(message=None):
    response = MessagingResponse()
    if message:
        response.message(message)
    return Response(str(response), mimetype="application/xml")


def register_whatsapp_webhook(app, download_portfolio, load_analyzer):
    print("inside register whatsapp webhook")
    """Register after app.py has defined its /chat route."""
    chat_view = app.view_functions["chat"]
    conversations = {}
    recent_messages = OrderedDict()
    lock = Lock()
    executor = ThreadPoolExecutor(max_workers=2)

    def run_task(conversation, text, loading, twilio, sender, recipient):
        file_path = conversation.file_path
        client_name = conversation.client_name
        try:
            if loading:
                downloaded = download_portfolio(text)
                if load_analyzer(downloaded) is None:
                    raise ValueError("Unable to parse portfolio")
                file_path = str(Path(downloaded).resolve())
                client_name = text
                message = _menu(client_name)
            else:
                # Reuse app.py's chatbot with the selected WhatsApp portfolio.
                with app.test_request_context("/chat", method="POST", json={"message": text}):
                    session["file_path"] = file_path
                    result = app.make_response(chat_view()).get_json()
                answer = result.get("answer") if result and result.get("success") else None
                if not isinstance(answer, str) or answer.startswith("Error contacting GroqCloud"):
                    answer = ""
                message = answer.strip() or UNAVAILABLE
        except Exception:
            app.logger.error("WhatsApp portfolio download or chat failed")
            message = ASK_NAME if loading else UNAVAILABLE
            if loading:
                message = "I couldn't load that portfolio. " + message

        try:
            for start in range(0, len(message), 1500):
                twilio.messages.create(
                    from_=recipient, to=sender, body=message[start:start + 1500]
                )
        except Exception:
            app.logger.error("Twilio could not send the WhatsApp reply")
        finally:
            with lock:
                conversation.file_path = file_path
                conversation.client_name = client_name
                conversation.busy = False

    @app.post(WEBHOOK_PATH)
    def whatsapp_webhook():
        public_url = os.environ.get("TWILIO_WHATSAPP_WEBHOOK_URL")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        if not all((public_url, auth_token, account_sid)):
            return Response(status=503)


        signature = request.headers.get("X-Twilio-Signature", "")

        if request.query_string:
            app.logger.warning("WhatsApp webhook: unexpected query string")
            return Response(status=403)

        if not signature:
            app.logger.warning("WhatsApp webhook: signature header missing")
            return Response(status=403)

        if not RequestValidator(auth_token.strip()).validate(
            public_url.strip(), request.form, signature
        ):
            app.logger.warning("WhatsApp webhook: signature mismatch")
            return Response(status=403)

        if request.form.get("AccountSid") != account_sid.strip():
            app.logger.warning("WhatsApp webhook: Account SID mismatch")
            return Response(status=403)

        sender = request.form.get("From", "")
        if not sender:
            wa_id = request.form.get("WaId", "")
            if re.fullmatch(r"[1-9][0-9]{1,14}", wa_id):
                sender = f"whatsapp:+{wa_id}"

        recipient = request.form.get("To", "")
        number = WHATSAPP_NUMBER.fullmatch(sender)
        message_sid = request.form.get("MessageSid")

        if not number or not WHATSAPP_NUMBER.fullmatch(recipient) or not message_sid:
            app.logger.warning("WhatsApp webhook: missing or invalid sender, recipient, or message SID")
            return Response(status=400)
        # These are trusted operators who may select portfolios by name.

        allowed_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "").strip()
        if number.group(1) != allowed_number:
            return _reply("This WhatsApp number isn't enabled for portfolio access.")


        text = request.form.get("Body", "").strip()
        with lock:
            if message_sid in recent_messages:
                return _reply()
            recent_messages[message_sid] = None
            if len(recent_messages) > 2048:
                recent_messages.popitem(last=False)

            conversation = conversations.get(sender)
            if conversation is None:
                conversations[sender] = Conversation()
                return _reply(ASK_NAME)
            if conversation.busy:
                return _reply("I'm still processing your previous message. Please wait for the reply.")
            command = text.casefold()
            if command in {"change", "reset"}:
                conversation.file_path = None
                conversation.client_name = None
                return _reply(ASK_NAME)
            if not text:
                return _reply(ASK_NAME if not conversation.file_path else "Please send a question as text.")

            if conversation.file_path and not Path(conversation.file_path).is_file():
                conversation.file_path = None
                conversation.client_name = None
                return _reply("Your portfolio file is no longer available. " + ASK_NAME)

            loading = conversation.file_path is None
            if command == "menu":
                return _reply(ASK_NAME if loading else _menu(conversation.client_name))
            if not loading and text.isdecimal():
                question = MENU_QUESTIONS.get(text)
                if question is None:
                    return _reply("Please choose a number from *menu*, or type your question.")
                text = question

            conversation.busy = True
            try:
                executor.submit(
                    run_task, conversation, text, loading,
                    Client(account_sid, auth_token), sender, recipient,
                )
            except Exception:
                conversation.busy = False
                app.logger.error("Could not schedule the WhatsApp request")
                return _reply(UNAVAILABLE)
        return _reply()

