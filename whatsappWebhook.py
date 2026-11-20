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
ASK_NAME = "Please enter the client name exactly as it appears on the website."
UNAVAILABLE = "I couldn't answer that question. Please try again."


@dataclass
class Conversation:
    file_path: str | None = None
    busy: bool = False


def _reply(message=None):
    response = MessagingResponse()
    if message:
        response.message(message)
    return Response(str(response), mimetype="application/xml")


def register_whatsapp_webhook(app, download_portfolio, load_analyzer):
    """Register after app.py has defined its /chat route."""
    chat_view = app.view_functions["chat"]
    conversations = {}
    recent_messages = OrderedDict()
    lock = Lock()
    executor = ThreadPoolExecutor(max_workers=2)

    def run_task(conversation, text, loading, twilio, sender, recipient):
        file_path = conversation.file_path
        try:
            if loading:
                downloaded = download_portfolio(text)
                if load_analyzer(downloaded) is None:
                    raise ValueError("Unable to parse portfolio")
                file_path = str(Path(downloaded).resolve())
                message = "Portfolio loaded. Send your question, or type CHANGE to load another client."
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
                conversation.busy = False

    @app.post(WEBHOOK_PATH)
    def whatsapp_webhook():
        public_url = os.environ.get("TWILIO_WHATSAPP_WEBHOOK_URL")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        if not all((public_url, auth_token, account_sid)):
            return Response(status=503)

        signature = request.headers.get("X-Twilio-Signature", "")
        if request.query_string or not RequestValidator(auth_token).validate(
            public_url, request.form, signature
        ):
            return Response(status=403)
        if request.form.get("AccountSid") != account_sid:
            return Response(status=403)

        sender = request.form.get("From", "")
        recipient = request.form.get("To", "")
        number = WHATSAPP_NUMBER.fullmatch(sender)
        message_sid = request.form.get("MessageSid")
        if not number or not WHATSAPP_NUMBER.fullmatch(recipient) or not message_sid:
            return Response(status=400)

        # These are trusted operators who may select portfolios by name.
        allowed = {phone.strip() for phone in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",")}
        if number.group(1) not in allowed:
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
            if text.casefold() in {"change", "reset"}:
                conversation.file_path = None
                return _reply(ASK_NAME)
            if not text:
                return _reply(ASK_NAME if not conversation.file_path else "Please send a question as text.")

            if conversation.file_path and not Path(conversation.file_path).is_file():
                conversation.file_path = None
                return _reply("Your portfolio file is no longer available. " + ASK_NAME)

            loading = conversation.file_path is None
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
