import utils.session
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pathlib import Path
from financialAnalyzer import FinancialAnalyzer
from dotenv import load_dotenv
import os
import subprocess
import sys
import datetime
import uuid
import threading
import logging
import urllib.parse
from groq import Groq
from playwright.sync_api import sync_playwright

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "qwen/qwen3.8-27b"
)

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None




app = Flask(__name__)

# Connect Flask's logger to Gunicorn handlers when running on Render / production
if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level if gunicorn_logger.level else logging.INFO)
else:
    logging.basicConfig(level=logging.INFO)

# Required for Flask sessions
app.secret_key = os.environ.get("SECRET_KEY", "financial-analyzer-secret-key")

# ============================================================
# SESSION LIFECYCLE MANAGEMENT
# Destroy session on server restart or browser close (not on refresh)
# ============================================================
SERVER_BOOT_ID = str(uuid.uuid4())

# Session cookies expire when the browser is closed
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.before_request
def enforce_server_boot_lifecycle():
    # Bypass static files so asset requests don't modify session
    if request.path.startswith("/static"):
        return

    # Check if the session was created on an older server instance (server restart)
    client_boot_id = session.get("server_boot_id")
    if client_boot_id is not None and client_boot_id != SERVER_BOOT_ID:
        # Server was restarted! Destroy all previous session data
        session.clear()

    # Store the current server boot ID
    session["server_boot_id"] = SERVER_BOOT_ID


@app.context_processor
def inject_session_lifecycle():
    return {
        "server_boot_id": SERVER_BOOT_ID,
        "is_portfolio_loaded": bool(session.get("file_path"))
    }


# ============================================================
# GLOBAL ERROR HANDLERS
# Ensure ALL errors return JSON — never HTML — so the frontend
# can always parse the response correctly.
# ============================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "error": "Endpoint not found."}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"success": False, "error": "Method not allowed."}), 405


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"success": False, "error": f"Internal server error: {str(e)}"}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all: return JSON for any unhandled exception."""
    import traceback
    print("Unhandled exception:", traceback.format_exc())
    return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# CONFIG
# ============================================================

URL = "https://www.money2management.com/"

DOWNLOAD_DIR = "Data" #join("/tmp", "Data")
USERNAME = os.environ.get("M2M_USERNAME")
PASSWORD = os.environ.get("M2M_PASSWORD")
EMAIL = os.environ.get("M2M_EMAIL")
_playwright_checked = False


# ============================================================
# IN-MEMORY JOB STORE
# Tracks background Playwright download jobs so the frontend
# can poll without holding a long-lived HTTP connection.
# ============================================================

# jobs[job_id] = {
#   "status": "pending" | "done" | "error",
#   "file_path": str | None,
#   "client_name": str,
#   "error": str | None
# }
jobs = {}



# ============================================================
# DOWNLOAD PORTFOLIO
# ============================================================

def run_server_download(client_name):


    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            accept_downloads=True
        )

        context.set_default_timeout(120000)

        context.set_default_navigation_timeout(
            120000
        )

        page = context.new_page()

        # ----------------------------------------------------
        # Open website
        # ----------------------------------------------------

        page.goto(URL)

        page.wait_for_selector(
            "input[type='text']"
        )

        # ----------------------------------------------------
        # Login
        # ----------------------------------------------------

        page.get_by_role(
            "textbox",
            name="Email"
        ).fill(EMAIL)

        page.get_by_role(
            "textbox",
            name="Username"
        ).fill(USERNAME)

        page.get_by_role(
            "textbox",
            name="Password"
        ).fill(PASSWORD)

        page.get_by_role(
            "button",
            name="Login"
        ).click()

        # ----------------------------------------------------
        # Portfolio Management
        # ----------------------------------------------------

        page.goto(
            "https://www.money2management.com/MF_MutualFundPortFoilo.aspx"
        )

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_rbtn_clienttype_1"
        )

        page.check(
            "#ctl00_ContentPlaceHolder1_rbtn_clienttype_1"
        )

        # ----------------------------------------------------
        # Wait for client dropdown
        # ----------------------------------------------------

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_drp_ClientName option[value]",
            state="attached"
        )

        page.wait_for_timeout(3000)

        options = page.locator(
            "#ctl00_ContentPlaceHolder1_drp_ClientName option"
        ).element_handles()

        selected_value = None

        # ----------------------------------------------------
        # 1. Exact match
        # ----------------------------------------------------

        for opt in options:

            text = opt.text_content()

            if text:

                parts = [
                    p.strip()
                    for p in text.split(" - ")
                ]

                extracted_name = (
                    parts[1]
                    if len(parts) >= 2
                    else text
                )

                norm_extracted = " ".join(
                    extracted_name.lower().split()
                )

                norm_client = " ".join(
                    client_name.lower().split()
                )

                if norm_extracted == norm_client:

                    selected_value = (
                        opt.get_attribute("value")
                    )

                    break

        # ----------------------------------------------------
        # 2. Full text exact
        # ----------------------------------------------------

        if not selected_value:

            for opt in options:

                text = opt.text_content()

                if text:

                    norm_text = " ".join(
                        text.lower().split()
                    )

                    norm_client = " ".join(
                        client_name.lower().split()
                    )

                    if norm_text == norm_client:

                        selected_value = (
                            opt.get_attribute("value")
                        )

                        break

        # ----------------------------------------------------
        # 3. Partial fallback
        # ----------------------------------------------------

        if not selected_value:

            for opt in options:

                text = opt.text_content()

                if text:

                    norm_text = " ".join(
                        text.lower().split()
                    )

                    norm_client = " ".join(
                        client_name.lower().split()
                    )

                    if norm_client in norm_text:

                        selected_value = (
                            opt.get_attribute("value")
                        )

                        break

        # ----------------------------------------------------
        # Client not found
        # ----------------------------------------------------

        if not selected_value:

            browser.close()

            raise Exception(
                f"Could not find client matching '{client_name}'"
            )

        # ----------------------------------------------------
        # Select client
        # ----------------------------------------------------

        page.evaluate(
            f"""
            const el = document.getElementById(
                'ctl00_ContentPlaceHolder1_drp_ClientName'
            );

            el.value = '{selected_value}';

            el.dispatchEvent(
                new Event('change')
            );
            """
        )

        page.wait_for_selector(
            "#ctl00_ContentPlaceHolder1_btn_export_excel"
        )

        # ----------------------------------------------------
        # Download Excel
        # ----------------------------------------------------

        with page.expect_download(
            timeout=120000
        ) as download_info:

            page.locator(
                "#ctl00_ContentPlaceHolder1_btn_export_excel"
            ).click()

        download = download_info.value

        os.makedirs(
            DOWNLOAD_DIR,
            exist_ok=True
        )

        today_str = datetime.datetime.now().strftime(
            "%Y-%m-%d"
        )

        safe_name = "".join(
            c if c.isalnum() else "_"
            for c in client_name
        )

        file_path = os.path.join(
            DOWNLOAD_DIR,
            f"Portfolio_{safe_name}_{today_str}.xls"
        )

        download.save_as(file_path)

        browser.close()

        return file_path


# ============================================================
# LOAD ANALYZER
# ============================================================

def load_analyzer(file_path):

    try:

        analyzer = FinancialAnalyzer(
            Path(file_path)
        )

        return analyzer

    except Exception as e:

        print(
            "Error loading portfolio:",
            e
        )

        return None


# ============================================================
# ROOT REDIRECT (PORTFOLIO DASHBOARD FIRST ON STARTUP)
# ============================================================

@app.route("/")
def root():
    """Open portfolio dashboard first on startup."""
    return redirect(url_for("portfolio_dashboard"))


# ============================================================
# ADVISOR CHATBOT PAGE
# ============================================================

@app.route("/bot")
@app.route("/advisor")
def home():
    file_path = session.get("file_path")
    client_name = session.get("client_name")
    is_loaded = bool(file_path and Path(file_path).is_file())

    return render_template(
        "index.html",
        portfolio_loaded=is_loaded,
        client_name=client_name or "",
        prefill_query=request.args.get("q", "").strip()
    )


# ============================================================
# PORTFOLIO DASHBOARD PAGE
# ============================================================

@app.route("/portfolio-dashboard")
@app.route("/portfolioDashboard")
@app.route("/dashboard")
def portfolio_dashboard():
    file_path = session.get("file_path")
    client_name = session.get("client_name")

    if not file_path or not Path(file_path).is_file():
        return render_template(
            "portfolioDashboard.html",
            portfolio_loaded=False,
            client_name=client_name or "",
            dashboard_data=None
        )

    analyzer = load_analyzer(file_path)
    if analyzer is None:
        return render_template(
            "portfolioDashboard.html",
            portfolio_loaded=False,
            client_name=client_name or "",
            dashboard_data=None,
            error="Could not load portfolio data."
        )

    dashboard_data = analyzer.get_dashboard_data()
    return render_template(
        "portfolioDashboard.html",
        portfolio_loaded=True,
        client_name=dashboard_data["client_name"],
        dashboard_data=dashboard_data
    )


# ============================================================
# SCHEME DETAILS PAGE
# ============================================================

@app.route("/scheme/<path:scheme_name>")
@app.route("/scheme-details")
def scheme_details(scheme_name=None):
    if not scheme_name:
        scheme_name = request.args.get("name", "").strip()

    if not scheme_name:
        return redirect(url_for("portfolio_dashboard"))

    scheme_name = urllib.parse.unquote(scheme_name)

    file_path = session.get("file_path")
    client_name = session.get("client_name")

    if not file_path or not Path(file_path).is_file():
        return redirect(url_for("portfolio_dashboard"))

    analyzer = load_analyzer(file_path)
    if analyzer is None:
        return redirect(url_for("portfolio_dashboard"))

    details = analyzer.get_scheme_details(scheme_name)
    if not details:
        return redirect(url_for("portfolio_dashboard"))

    return render_template(
        "scheme_details.html",
        client_name=details["client_name"],
        valuation_date=details["valuation_date"],
        details=details
    )


# ============================================================
# FETCH CLIENT PORTFOLIO
# ============================================================

@app.route(
    "/fetch-portfolio",
    methods=["POST"]
)
def fetch_portfolio():

    client_name = request.form.get(
        "client_name",
        ""
    ).strip()

    if not client_name:

        return jsonify({
            "success": False,
            "error": "Please enter client name."
        })

    try:

        # ----------------------------------------------------
        # Download Excel
        # ----------------------------------------------------

        file_path = run_server_download(
            client_name
        )

        # ----------------------------------------------------
        # Load FinancialAnalyzer
        # ----------------------------------------------------

        analyzer = load_analyzer(
            file_path
        )

        if analyzer is None:

            return jsonify({
                "success": False,
                "error": "Could not parse portfolio data."
            })

        # ----------------------------------------------------
        # Generate session ID
        # ----------------------------------------------------

        portfolio_id = str(
            uuid.uuid4()
        )

        session["portfolio_id"] = portfolio_id

        session["file_path"] = file_path

        session["client_name"] = client_name

        session["chat_history"] = []

        return jsonify({
            "success": True,
            "client_name": client_name,
            "message": "Portfolio loaded successfully."
        })

    except Exception as e:

        import traceback
        print("fetch_portfolio error:", traceback.format_exc())

        # Always return JSON so the browser never receives an HTML error page
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# BACKGROUND JOB: START FETCH (non-blocking)
# Returns a job_id immediately. The heavy Playwright work runs
# in a background thread. Frontend polls /job-status/<job_id>.
# This avoids Render's 30-second HTTP proxy timeout.
# ============================================================

def _run_job(job_id, client_name):
    """Worker function that runs in a background thread."""
    try:
        file_path = run_server_download(client_name)
        jobs[job_id]["file_path"] = file_path
        jobs[job_id]["status"] = "done"
    except Exception as e:
        import traceback
        print(f"Job {job_id} failed:", traceback.format_exc())
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["status"] = "error"


@app.route(
    "/start-fetch",
    methods=["POST"]
)
def start_fetch():

    client_name = request.form.get(
        "client_name", ""
    ).strip()

    if not client_name:
        return jsonify({
            "success": False,
            "error": "Please enter client name."
        })

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "pending",
        "client_name": client_name,
        "file_path": None,
        "error": None
    }

    t = threading.Thread(
        target=_run_job,
        args=(job_id, client_name),
        daemon=True
    )
    t.start()

    return jsonify({
        "success": True,
        "job_id": job_id
    })


# ============================================================
# POLL JOB STATUS
# ============================================================

@app.route(
    "/job-status/<job_id>",
    methods=["GET"]
)
def job_status(job_id):

    job = jobs.get(job_id)

    if not job:
        return jsonify({
            "success": False,
            "error": "Job not found."
        }), 404

    status = job["status"]

    if status == "pending":
        return jsonify({
            "success": True,
            "status": "pending"
        })

    if status == "error":
        # Clean up
        jobs.pop(job_id, None)
        return jsonify({
            "success": False,
            "error": job["error"]
        })

    # status == "done" — load into session
    file_path = job["file_path"]
    client_name = job["client_name"]

    analyzer = load_analyzer(file_path)

    if analyzer is None:
        jobs.pop(job_id, None)
        return jsonify({
            "success": False,
            "error": "Could not parse portfolio data."
        })

    session["portfolio_id"] = str(uuid.uuid4())
    session["file_path"] = file_path
    session["client_name"] = client_name
    session["chat_history"] = []

    jobs.pop(job_id, None)

    return jsonify({
        "success": True,
        "status": "done",
        "client_name": client_name,
        "message": "Portfolio loaded successfully."
    })


# ============================================================
# GET PORTFOLIO DATA
# ============================================================

@app.route(
    "/portfolio",
    methods=["GET"]
)
def portfolio():


    file_path = session.get(
        "file_path"
    )

    client_name = session.get(
        "client_name"
    )

    if not file_path:

        return jsonify({
            "success": False,
            "error": "No portfolio loaded."
        })

    analyzer = load_analyzer(
        file_path
    )

    if analyzer is None:

        return jsonify({
            "success": False,
            "error": "Could not load portfolio."
        })

    portfolio_data = analyzer.portfolio_data

    holders_list = []

    if "holders" in portfolio_data:

        holders_list = [
            h["Holder Name"]
            for h in portfolio_data["holders"]
            if h.get("Holder Name")
        ]

    # --------------------------------------------------------
    # KPI calculations
    # --------------------------------------------------------

    total_sip = sum(
        float(h.get("SIP") or 0)
        for h in portfolio_data.get(
            "holders",
            []
        )
    )

    total_cost = sum(
        float(h.get("Cost of Investment") or 0)
        for h in portfolio_data.get(
            "holders",
            []
        )
    )

    total_current = sum(
        float(h.get("Current Value") or 0)
        for h in portfolio_data.get(
            "holders",
            []
        )
    )

    weighted_xirr_sum = sum(
        float(h.get("XIRR") or 0)
        *
        float(h.get("Current Value") or 0)
        for h in portfolio_data.get(
            "holders",
            []
        )
    )

    avg_xirr = (
        weighted_xirr_sum / total_current
        if total_current > 0
        else 0
    )

    net_gain = (
        total_current - total_cost
    )

    gain_percentage = (
        net_gain / total_cost * 100
        if total_cost > 0
        else 0
    )

    return jsonify({

        "success": True,

        "client_name": client_name,

        "holders": holders_list,

        "metrics": {

            "total_sip": total_sip,

            "total_cost": total_cost,

            "total_current": total_current,

            "avg_xirr": avg_xirr,

            "net_gain": net_gain,

            "gain_percentage": gain_percentage

        }

    })


# ============================================================
# CHATBOT
# ============================================================

@app.route(
    "/chat",
    methods=["POST"]
)
def chat():

    data = request.get_json()

    actual_query = data.get(
        "message",
        ""
    ).strip()

    if not actual_query:

        return jsonify({
            "success": False,
            "error": "Please enter a question."
        })

    # --------------------------------------------------------
    # Load analyzer
    # --------------------------------------------------------

    file_path = session.get(
        "file_path"
    )

    if not file_path:

        return jsonify({
            "success": False,
            "error": "Please load a portfolio first."
        })

    analyzer = load_analyzer(
        file_path
    )

    if analyzer is None:

        return jsonify({
            "success": False,
            "error": "Could not load portfolio."
        })

    portfolio = analyzer.portfolio_data

    # --------------------------------------------------------
    # Extract holders
    # --------------------------------------------------------

    holders_list = []

    if "holders" in portfolio:

        holders_list = [
            h["Holder Name"]
            for h in portfolio["holders"]
            if h.get("Holder Name")
        ]

    # --------------------------------------------------------
    # Name Detection from query text
    # --------------------------------------------------------

    detected_name = None

    query_lower = actual_query.lower()

    for holder in holders_list:

        for part in holder.split():

            if (
                len(part) > 2
                and part.lower()
                in query_lower
            ):

                detected_name = holder

                break

        if detected_name:

            break

    # --------------------------------------------------------
    # Build context-aware system prompt
    # --------------------------------------------------------

    if detected_name:

        compact_data = (
            analyzer
            ._generate_compact_summary_for_holder(
                detected_name
            )
        )

        system_prompt = (

            f"You are a Mutual Fund Advisor "
            f"exclusively assisting {detected_name}.\n"

            f"IMPORTANT: Only answer based on "
            f"{detected_name}'s data below. "

            f"Do NOT include or mention any other "
            f"family member's data.\n\n"

            f"{compact_data}\n\n"

            "Rules:\n"

            "- Use ONLY exact figures from the data above.\n"

            "- Address the client by their first name.\n"

            "- Be concise and professional.\n"

            f"- If the query is about someone else entirely, "
            f"politely clarify that you only have "
            f"{detected_name}'s data loaded."

        )

        rich_query = (
            f"[Client: {detected_name}] "
            f"{actual_query}"
        )

    else:

        compact_data = (
            analyzer
            ._generate_compact_summary()
        )

        system_prompt = (

            "You are a Mutual Fund Advisor "
            "for the entire family portfolio.\n"

            f"{compact_data}\n\n"

            "Rules: Use exact figures from above data. "
            "Be concise. Address clients by name."

        )

        rich_query = (
            "[Context: All Family Members] "
            f"{actual_query}"
        )

    # --------------------------------------------------------
    # GroqCloud
    # --------------------------------------------------------

    try:

        client = groq_client or Groq(api_key=os.getenv("GROQ_API_KEY"))

        response = client.chat.completions.create(

            model=GROQ_MODEL,

            messages=[

                {
                    "role": "system",
                    "content": system_prompt
                },

                {
                    "role": "user",
                    "content": rich_query
                }

            ],

            max_tokens=2048,

        )

        full_response = (
            response.choices[0].message.content
        )
        
        app.logger.info(f"Groq finish reason: {response.choices[0].finish_reason}")
        app.logger.info(f"Groq response length: {len(response.choices[0].message.content or '')}")

    except Exception as e:
        app.logger.exception(f"Groq API error: {e}")
        full_response = (
            f"Error contacting GroqCloud ({GROQ_MODEL}): {e}."
        )

    # --------------------------------------------------------
    # Save history
    # --------------------------------------------------------

    if "chat_history" not in session:

        session["chat_history"] = []

    session["chat_history"].append({

        "role": "user",

        "text": actual_query

    })

    session["chat_history"].append({

        "role": "bot",

        "text": full_response

    })

    session.modified = True

    return jsonify({

        "success": True,

        "question": actual_query,

        "answer": full_response,

        "detected_name": detected_name

    })


# ============================================================
# RESET CLIENT
# ============================================================

@app.route(
    "/reset",
    methods=["POST"]
)
def reset():

    session.clear()

    return jsonify({
        "success": True
    })


try:
    from whatsappWebhook import register_whatsapp_webhook
    register_whatsapp_webhook(app, run_server_download, load_analyzer)
except Exception as e:
    app.logger.warning(f"WhatsApp webhook not registered (PostgreSQL/libpq unavailable): {e}")

# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    # Automatically open Portfolio Dashboard in browser on startup
    import webbrowser
    import threading

    def open_browser():
        try:
            webbrowser.open_new("http://127.0.0.1:5000/dashboard")
        except Exception:
            pass

    threading.Timer(1.25, open_browser).start()

    # NOTE: use_reloader=False is required because Playwright's
    # sync_playwright is incompatible with Werkzeug's auto-reloader
    # on Windows — the reloader forks a child process that breaks
    # the Chromium browser launch, causing "Failed to fetch".
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False
    )