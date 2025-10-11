import os
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, redirect
from collections import deque
from flask_cors import CORS
from dotenv import load_dotenv

# Import chat logging functions
from chat import init_db, log_message, get_session_logs

# Import your existing functions
from medical_qna import (
    binary_emergency_check, 
    analyze_and_respond, 
    classify_answer_to_digit,
    medical_summary,
    QUESTIONS,
    OPTIONS,
    INTENT_LABELS,
    CONSULTANT_MAP,
    default_time_slots,
    next_three_dates_from_tomorrow
)

load_dotenv()

app = Flask(__name__)
# Optional frontend URL for production redirects/CORS
FRONTEND_URL = os.environ.get("FRONTEND_URL")
# Optional token to view CSP reports via HTTP (set in Render dashboard)
CSP_REPORT_VIEW_TOKEN = os.environ.get("CSP_REPORT_VIEW_TOKEN")

# Build CORS origins dynamically
cors_origins = [
    "http://localhost:3000",  # Local development
    "http://localhost:5173",  # Vite dev server
    "https://vaidhya-6t0w.onrender.com",  # Your live frontend
    "https://*.onrender.com", # Other Render deployments
]
if FRONTEND_URL:
    cors_origins.append(FRONTEND_URL)

CORS(app, origins=cors_origins)  # Enable CORS for web frontend

# Initialize database
init_db()

# Store bot sessions
bot_sessions = {}

class WebMedicalBot:
    def __init__(self):
        self.state = {
            "intent": None,
            "entities": {},
            "q_index": 0,
            "answers": {},
            "user_info": {"name": None, "age": None},
            "awaiting_post_summary": False,
            "awaiting_booking_date": False,
            "awaiting_booking_slot": False,
            "available_booking_dates": [],
            "available_booking_slots": [],
            "selected_booking_date": None,
            "booking_date": None,
            "booking_time": None
        }

    def process_message(self, message):
        """Main message processing - synchronous version of your bot logic"""
        
        print(f"🗨️ User said: {message}")
        
        # Emergency check
        if binary_emergency_check(message):
            self.reset_state()
            return {
                "text": "🚨 This looks like an emergency. Please call your local emergency number immediately!",
                "type": "emergency",
                "buttons": []
            }

        # Booking slot selection
        if self.state.get("awaiting_booking_slot"):
            raw = message.strip()
            chosen_date = None
            chosen_time = None
            
            if re.fullmatch(r"\s*[1-3]\s*", raw):
                idx = int(raw.strip())
                try:
                    chosen_time = self.state["available_booking_slots"][idx-1][1]  # time_str
                    chosen_date = self.state.get("selected_booking_date")
                except Exception:
                    chosen_time = None

            if chosen_date and chosen_time:
                self.state["booking_date"] = chosen_date
                self.state["booking_time"] = chosen_time
                self.state["intent"] = "BookAppointment"
                self.state["awaiting_booking_slot"] = False
                self.state["awaiting_booking_date"] = False
                self.state["awaiting_post_summary"] = False
                
                # Find friendly time
                friendly_time = chosen_time
                for label, ts in default_time_slots():
                    if ts == chosen_time:
                        friendly_time = label
                        break
                
                return {
                    "text": f"📅 You've selected an appointment for {chosen_date} at {friendly_time}.\n\nPay and confirm slot: [Click here](https://your-booking-url.com)",
                    "type": "booking_confirmed",
                    "buttons": []
                }
            else:
                return {
                    "text": "Please select one of the time options (1/2/3).",
                    "type": "error",
                    "buttons": [{"text": f"{i}", "value": str(i)} for i in range(1, 4)]
                }

        # Booking date selection
        if self.state.get("awaiting_booking_date"):
            raw = message.strip()
            chosen_date = None
            
            if re.fullmatch(r"\s*[1-3]\s*", raw):
                idx = int(raw.strip())
                try:
                    chosen_date = self.state["available_booking_dates"][idx-1][1]
                except Exception:
                    chosen_date = None

            if chosen_date:
                # Show time slots for chosen date
                slots = default_time_slots()
                self.state["available_booking_slots"] = slots
                self.state["selected_booking_date"] = chosen_date
                self.state["awaiting_booking_date"] = False
                self.state["awaiting_booking_slot"] = True
                
                buttons = []
                for i, (label, _) in enumerate(slots, start=1):
                    buttons.append({"text": f"{i}. {label}", "value": str(i)})
                
                return {
                    "text": f"Select your preferred time for {chosen_date}:",
                    "type": "time_selection",
                    "buttons": buttons
                }
            else:
                return {
                    "text": "Please select one of the date options (1/2/3).",
                    "type": "error",
                    "buttons": [{"text": f"{i}", "value": str(i)} for i in range(1, 4)]
                }

        # Post-summary options
        if self.state.get("awaiting_post_summary"):
            lc = message.lower()
            if any(word in lc for word in ["yes", "book", "appointment"]):
                self.state["awaiting_post_summary"] = False
                dates = next_three_dates_from_tomorrow("Asia/Kolkata")
                self.state["available_booking_dates"] = dates
                self.state["awaiting_booking_date"] = True
                
                text_lines = ["Please pick a date for your appointment:"]
                buttons = []
                for i, (label, iso_date) in enumerate(dates, start=1):
                    text_lines.append(f"{i}) {label} — {iso_date}")
                    buttons.append({"text": f"{i}", "value": str(i)})
                
                return {
                    "text": "\n".join(text_lines),
                    "type": "date_selection",
                    "buttons": buttons
                }
            
            return {
                "text": "Please tap the 'Book Appointment' button or type 'book'.",
                "type": "booking_prompt",
                "buttons": [{"text": "Book Appointment", "value": "book"}]
            }

        # Name collection
        if self.state["user_info"]["name"] is None:
            match = re.search(r"(?:my name is|i am|i'm)\s+(.+)", message, flags=re.I)
            if match:
                name = match.group(1).strip()
            else:
                name = message.strip()

            self.state["user_info"]["name"] = name or "Patient"
            return {
                "text": f"😊 Nice to meet you, {self.state['user_info']['name']}!\nNow, could you please tell me your age?",
                "type": "question",
                "buttons": []
            }

        # Age collection
        if self.state["user_info"]["age"] is None:
            match = re.search(r"(\d{1,3})", message)
            if match:
                age = match.group(1)
            else:
                age = message.strip()

            self.state["user_info"]["age"] = age
            return {
                "text": f"✅ Thanks {self.state['user_info']['name']}. I have noted your age as {age}.\nNow, please describe your main symptom in a sentence.",
                "type": "question",
                "buttons": []
            }

        # Intent processing
        if not self.state["intent"]:
            result = analyze_and_respond(message)
            intent = result.get("intent", "CheckSymptoms")
            entities = result.get("entities", {})
            
            print(f"🔍 LLM Analysis: '{message}' → Intent: {intent}, Entities: {entities}")

            allowed = {"Greeting", "CheckSymptoms", "BookAppointment", "CancelAppointment", "RescheduleAppointment", "Goodbye"}
            if intent not in allowed:
                intent = "OutOfScope"

            if intent == "OutOfScope":
                print(f"🚫 Handling OutOfScope for: '{message}'")
                return {
                    "text": "I'm a medical assistant focused on health symptoms and appointments. Is there anything health-related I can help you with?",
                    "type": "outofscope",
                    "buttons": [
                        {"text": "Check Symptoms", "value": "I have pain"},
                        {"text": "Book Appointment", "value": "book appointment"}
                    ]
                }

            self.state["intent"] = intent
            self.state["entities"] = entities
            print(f"✅ Set intent to: {intent}")

            if self.state["intent"] == "CheckSymptoms":
                response = {
                    "text": "Thanks for sharing. Let's go through a quick symptom assessment.\n🩺 Let's do a short assessment about your daily activities.",
                    "type": "assessment_start"
                }
                
                # Add first question
                question_data = self.get_current_question()
                if question_data:
                    response["text"] += f"\n\n{question_data['text']}"
                    response["buttons"] = question_data["buttons"]
                
                return response

        # Questionnaire processing
        if self.state["intent"] == "CheckSymptoms":
            return self.process_questionnaire_answer(message)

        return {
            "text": "Sorry — I didn't understand that. Could you rephrase?",
            "type": "unclear",
            "buttons": []
        }

    def get_current_question(self):
        q_index = self.state["q_index"]
        if q_index < len(QUESTIONS):
            question_text = f"**Question {q_index+1} of {len(QUESTIONS)}:** {QUESTIONS[q_index]}"
            options_text = "\n".join(OPTIONS)
            
            buttons = [{"text": str(i), "value": str(i)} for i in range(1, 6)]
            
            return {
                "text": f"{question_text}\n\n{options_text}\n\n(Tap a number button or type 1-5)",
                "buttons": buttons
            }
        return None

    def process_questionnaire_answer(self, message):
        q_index = self.state["q_index"]
        
        if q_index < len(QUESTIONS):
            digit = classify_answer_to_digit(message)
            question_text = QUESTIONS[q_index]
            self.state["answers"][question_text] = digit
            print(f"📥 Recorded answer: Q{q_index+1}='{question_text}' -> {digit}")

        self.state["q_index"] += 1

        if self.state["q_index"] < len(QUESTIONS):
            # Next question
            question_data = self.get_current_question()
            return {
                "text": question_data["text"],
                "type": "question",
                "buttons": question_data["buttons"],
                "progress": f"{self.state['q_index']}/{len(QUESTIONS)}"
            }
        else:
            # Assessment complete
            return self.generate_summary()

    def generate_summary(self):
        answers = self.state.get("answers", {})
        if not answers:
            return {
                "text": "No answers recorded.",
                "type": "error",
                "buttons": []
            }

        overall = max(answers.values())
        label = INTENT_LABELS.get(overall, "Difficulty/Moderate")
        consultant = CONSULTANT_MAP.get(overall, "Occupational Therapist")

        data_for_summary = {
            "user": self.state["user_info"],
            "entities": self.state["entities"],
            "answers": answers
        }
        summary_text = medical_summary(data_for_summary)

        full_text = (
            f"✨ Thank you for completing the assessment!\n\n"
            f"📝 Summary & Recommendation:\n\n{summary_text}\n\n"
            f"Overall level: **{label.split('/')[-1]}**.\n"
            f"Recommended specialist: **{consultant}**.\n\n"
            f"Would you like me to: Book an appointment\n"
            f"(Tap the button below)"
        )

        self.state["awaiting_post_summary"] = True
        self.state["intent"] = "PostSummaryOptions"

        return {
            "text": full_text,
            "type": "summary",
            "buttons": [{"text": "Book Appointment", "value": "book"}]
        }

    def reset_state(self):
        self.state = {
            "intent": None,
            "entities": {},
            "q_index": 0,
            "answers": {},
            "user_info": {"name": None, "age": None},
            "awaiting_post_summary": False,
            "awaiting_booking_date": False,
            "awaiting_booking_slot": False,
            "available_booking_dates": [],
            "available_booking_slots": [],
            "selected_booking_date": None,
            "booking_date": None,
            "booking_time": None
        }

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        
        # Get or create bot instance for this session
        if session_id not in bot_sessions:
            bot_sessions[session_id] = WebMedicalBot()
        
        bot = bot_sessions[session_id]
        
        # Log user message
        log_message(session_id, 'user', user_message)
        
        # Process message
        response = bot.process_message(user_message)
        
        # Log bot response
        log_message(session_id, 'bot', response.get('text', ''))
        
        return jsonify({
            'response': response,
            'session_id': session_id,
            'status': 'success'
        })
        
    except Exception as e:
        print(f"❌ Error in /api/chat: {str(e)}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/api/reset', methods=['POST'])
def reset_session():
    try:
        data = request.get_json()
        session_id = data.get('session_id', 'default')
        
        if session_id in bot_sessions:
            bot_sessions[session_id].reset_state()
        
        return jsonify({
            'message': 'Session reset successfully',
            'status': 'success'
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "service": "medical-bot-backend",
        "timestamp": datetime.now().isoformat()
    })

# Keep a small, in-memory ring buffer of recent CSP reports for easy inspection
_CSP_REPORTS = deque(maxlen=200)

@app.route('/csp-report', methods=['POST'])
def csp_report():
    """Receive CSP violation reports from browsers and log them for debugging."""
    try:
        # Some browsers send application/csp-report, others application/reports+json
        data = request.get_json(silent=True, force=False) or {}
        # Normalize common shapes
        report = data.get('csp-report') or data.get('csp_report') or data
        normalized = {
            "ts": datetime.now().isoformat(),
            "ua": request.headers.get('User-Agent'),
            "report": report,
        }
        _CSP_REPORTS.append(normalized)
        print("⚠️ CSP Violation Report:", json.dumps(normalized, indent=2))
    except Exception as e:
        print(f"⚠️ CSP report parse error: {e}")
    # Always return 204 to avoid retries
    return ('', 204)

@app.route('/csp-reports', methods=['GET'])
def csp_reports():
    """Optional: fetch recent CSP reports (requires CSP_REPORT_VIEW_TOKEN)."""
    if not CSP_REPORT_VIEW_TOKEN:
        return jsonify({"error": "CSP report viewing not enabled"}), 403
    token = request.args.get('token')
    if token != CSP_REPORT_VIEW_TOKEN:
        return jsonify({"error": "invalid token"}), 403
    return jsonify(list(_CSP_REPORTS))

@app.route('/', methods=['GET'])
def root():
    # In production, direct users to the actual frontend URL instead of showing API JSON
    if FRONTEND_URL:
        return redirect(FRONTEND_URL, code=302)

    # Default local/dev response
    return jsonify({
        "message": "Medical Bot API is running",
        "status": "active",
        "endpoints": [
            "/api/chat",
            "/api/reset", 
            "/health"
        ]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print(f"Starting Web Medical Bot API on port {port}")
    print(f"Debug mode: {debug}")
    print(f"FRONTEND_URL: {FRONTEND_URL}")
    print(f"CSP_REPORT_VIEW_TOKEN set: {bool(CSP_REPORT_VIEW_TOKEN)}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)