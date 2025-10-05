import os
import json
import traceback
import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from chat import init_db, log_message

# Load environment variables from .env file
load_dotenv()
init_db()


import google.generativeai as genai

from aiohttp import web
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    ConversationState,
    MemoryStorage,
    BotFrameworkAdapter,
    ActivityHandler,
    TurnContext
)
from botbuilder.schema import (
    SuggestedActions, 
    CardAction, 
    ActionTypes, 
    Activity, 
    ActivityTypes, 
    Attachment,
    ChannelAccount
)
from typing import List

# ---------- Configuration ----------

# Get API key from environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required but not set")

genai.configure(api_key=GEMINI_API_KEY)

# Microsoft Bot Framework app id/password (optional for local dev)
APP_ID = os.environ.get("MicrosoftAppId", "")
APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")

# ---------- Questionnaire (unchanged) ----------
QUESTIONS = [
    "Open a tight or new jar",
    "Write",
    "Turn a key",
    "Prepare a meal",
    "Carry a shopping bag"
]

OPTIONS = [
    "1. No Difficulty",
    "2. Mild Difficulty",
    "3. Moderate Difficulty",
    "4. Severe Difficulty",
    "5. Unable To Do"
]

INTENT_LABELS = {
    1: "Difficulty/NoDifficulty",
    2: "Difficulty/Mild",
    3: "Difficulty/Moderate",
    4: "Difficulty/Severe",
    5: "Difficulty/Unable"
}

CONSULTANT_MAP = {
    1: "Self-care / Advice",
    2: "Physiotherapist / Occupational Therapist",
    3: "Occupational Therapist (consider specialist referral)",
    4: "Surgeon + Occupational Therapist",
    5: "Urgent Medical Attention"
}

# ---------- LLM helpers ----------
def _gemini_model():
    return genai.GenerativeModel("gemini-2.0-flash")

def binary_emergency_check(user_input: str) -> bool:
    model = _gemini_model()
    prompt = f"""Does this message describe a medical emergency
(severe chest pain, difficulty breathing, unconscious, bleeding, stroke, etc.)?

Input: "{user_input}"

Respond ONLY with:
1
0
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip() == "1"
    except Exception:
        return False

def analyze_and_respond(user_input: str) -> dict:
    model = _gemini_model()
    prompt = f"""
You are an advanced NLU assistant for a medical clinic.

### INSTRUCTIONS
1. Always classify input into one of:
   - Greeting (hi, hello, good morning)
   - CheckSymptoms (health issues, pain, medical problems)
   - BookAppointment (book, schedule, appointment)
   - CancelAppointment (cancel appointment)
   - RescheduleAppointment (reschedule, change appointment)
   - Goodbye (bye, goodbye, thanks)
   - OutOfScope (sports, weather, cooking, non-medical topics)

2. PRIORITY RULES (MOST IMPORTANT):
   - IF input contains ANY medical symptoms/health issues → CheckSymptoms
   - Examples: "I want to play but have headache" → CheckSymptoms
   - Examples: "I like cooking but my back hurts" → CheckSymptoms
   - Examples: "riding bike causes knee pain" → CheckSymptoms
   - ONLY classify as OutOfScope if NO medical content exists

3. STRICT RULES:
   - Medical symptoms ALWAYS take priority over other topics
   - Pain, ache, hurt, symptoms, illness → CheckSymptoms
   - Only pure non-medical topics → OutOfScope
   - Appointment-related requests → respective appointment intents

4. For CheckSymptoms, extract the medical symptom and return empty response

Return JSON only. Examples:
{{"intent":"CheckSymptoms", "entities": {{"symptom": "back pain", "date": null, "time": null, "relative_date": null}}, "response":""}}
{{"intent":"OutOfScope", "entities": {{"symptom": null, "date": null, "time": null, "relative_date": null}}, "response":""}}

User: "{user_input}"
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean up JSON response (remove markdown code blocks if present)
        if text.startswith("```json"):
            text = text.replace("```json", "").replace("```", "").strip()
        
        return json.loads(text)
    except Exception as e:
        print(f"LLM Error: {e}")
        # Better fallback - check for medical keywords
        medical_keywords = ["pain", "hurt", "ache", "sick", "symptom", "headache", "backache", "chest", "stomach", "fever", "cough", "dizzy"]
        if any(keyword in user_input.lower() for keyword in medical_keywords):
            return {
                "intent": "CheckSymptoms",
                "entities": {"symptom": user_input, "date": None, "time": None, "relative_date": None},
                "response": ""
            }
        else:
            return {
                "intent": "OutOfScope",
                "entities": {"symptom": None, "date": None, "time": None, "relative_date": None},
                "response": ""
            }

def classify_answer_to_digit(user_text: str) -> int:
    stripped = (user_text or "").strip()
    if stripped:
        first_token = stripped.split()[0].strip().strip(".")
        if first_token.isdigit():
            val = int(first_token)
            if 1 <= val <= 5:
                return val

    model = _gemini_model()
    prompt = f"""
You are a classifier that maps a short user reply about difficulty performing an activity to a numeric severity 1..5.
Return ONLY the digit (1,2,3,4,5) and nothing else.

Mapping:
1 -> No Difficulty
2 -> Mild Difficulty
3 -> Moderate Difficulty
4 -> Severe Difficulty
5 -> Unable To Do

Examples:
User: "I can open jars easily, no problem." -> 1
User: "I can open, but it needs some effort" -> 2
User: "I struggle and sometimes can't open without help" -> 3
User: "I practically can't open it and need assistance" -> 4
User: "I cannot open jars at all" -> 5

Now classify:
User: "{user_text}"
"""
    try:
        resp = model.generate_content(prompt)
        digit = resp.text.strip().split()[0]
        val = int(digit)
        if 1 <= val <= 5:
            return val
    except Exception:
        pass

    return 3

def medical_summary(data: dict) -> str:
    model = _gemini_model()
    prompt = f"""
Patient info: {json.dumps(data, indent=2)}

### INSTRUCTIONS
As a medical assistant, analyze the patient's symptoms and questionnaire responses:

1. Primary Focus: Patient's reported symptom (if any)
2. Secondary: Activity assessment scores
3. Recommend specialists based on SYMPTOM FIRST, then activity scores
4. Common specialist mappings:
   - Stomach/Digestive issues → Gastroenterologist
   - Joint/Muscle pain → Orthopedist
   - Hand/Wrist issues → Hand Surgeon
   - Chest pain → Cardiologist
   - Breathing issues → Pulmonologist
   - General symptoms → Internal Medicine

Format response as:
📋 Assessment:
<Brief analysis of primary symptom and functional limitations>

👨‍⚕️ Recommended specialist(s):
Primary: <Most appropriate specialist based on symptoms>
Alternative: <Secondary specialist if needed>

⚠️ This is not a medical diagnosis. Please consult a doctor for proper evaluation.
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return (
            "📋 Assessment:\n"
            "Based on your reported symptoms, further medical evaluation is recommended.\n\n"
            "👨‍⚕️ Recommended specialist:\n"
            "Primary: Internal Medicine Specialist\n\n"
            "⚠️ This is not a medical diagnosis. Please consult a doctor for proper evaluation."
        )

# ---------- Small helper to send suggested actions consistently ----------
def ActivityFactory_text_with_suggested_actions(text: str, suggested: SuggestedActions) -> Activity:
    return Activity(
        type=ActivityTypes.message,
        text=text,
        suggested_actions=suggested
    )

# ---------- Booking date/time helpers ----------
def next_three_dates_from_tomorrow(timezone_str: str = "Asia/Kolkata"):
    """
    Return list of tuples (label, iso_date) for tomorrow, day after, and next day.
    """
    tz = ZoneInfo(timezone_str)
    today = datetime.now(tz).date()
    results = []
    for i in range(1, 4):  # start at 1 => tomorrow
        d = today + timedelta(days=i)
        label = d.strftime("%a, %b %d, %Y")  # e.g., 'Tue, Sep 29, 2025'
        results.append((label, d.isoformat()))
    return results

def default_time_slots():
    """
    Return list of (label, time_str) for the three time slots.
    """
    # Use 24-hour ISO time for payload, show human-friendly title
    return [
        ("11:00 AM", "11:00"),
        ("01:00 PM", "13:00"),
        ("03:00 PM", "15:00")
    ]

# ---------- Bot logic ----------
class MedicalBot(ActivityHandler):
    def __init__(self, conversation_state: ConversationState):
        super().__init__()
        self.conversation_state = conversation_state
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
        self.greeted = False

    async def on_members_added_activity(
        self, members_added: List[ChannelAccount], turn_context: TurnContext
    ):
        """Send a welcome message when the user joins."""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await self.send_and_log(
                    turn_context,
                    "👋 Hi, I am Doctor's Assistant for a OrthoVaidhya Clinic suggest's consultant. What is your name?"
                )
                self.greeted = True

    async def send_and_log(self, turn_context: TurnContext, message: str):
        session_id = turn_context.activity.conversation.id
        log_message(session_id, "bot", message)
        await turn_context.send_activity(message)

    # -----------------------
    # Booking UI builders
    # -----------------------
    async def present_booking_dates(self, turn_context: TurnContext):
        dates = next_three_dates_from_tomorrow("Asia/Kolkata")
        self.state["available_booking_dates"] = dates
        
        # Create buttons for dates
        actions = []
        for idx, (label, iso_date) in enumerate(dates, start=1):
            actions.append(
                CardAction(
                    type=ActionTypes.im_back,
                    title=str(idx),  # Show just the number
                    value=str(idx)   # Send just the number when clicked
                )
            )

        # Format message text
        text_lines = ["Please pick a date for your appointment (tap a button or type 1/2/3):"]
        for i, (label, iso_date) in enumerate(dates, start=1):
            text_lines.append(f"{i}) {label} — {iso_date}")
        message_text = "\n".join(text_lines)

        # Create and send activity with buttons
        activity = Activity(
            type=ActivityTypes.message,
            text=message_text,
            suggested_actions=SuggestedActions(actions=actions)
        )
        await turn_context.send_activity(activity)
        
        # Update state
        self.state["awaiting_booking_date"] = True
        self.state["awaiting_booking_slot"] = False
        self.state["selected_booking_date"] = None

    async def present_time_slots_for_date(self, turn_context: TurnContext, iso_date: str):
        slots = default_time_slots()
        self.state["available_booking_slots"] = slots
        self.state["selected_booking_date"] = iso_date

        actions = []
        for idx, (label, time_str) in enumerate(slots, start=1):
            title = f"Time {idx}: {label}"
            actions.append(CardAction(type=ActionTypes.im_back, title=title, value=str(idx)))

        text_lines = [f"Select your preferred time for {iso_date}:"]
        for i, (label, _) in enumerate(slots, start=1):
            text_lines.append(f"{i}) {label}")
        message_text = "\n".join(text_lines)

        activity = Activity(
            type=ActivityTypes.message,
            text=message_text,
            suggested_actions=SuggestedActions(actions=actions)
        )
        await turn_context.send_activity(activity)
        
        self.state["awaiting_booking_date"] = False
        self.state["awaiting_booking_slot"] = True
        self.state["awaiting_booking_date"] = False
        self.state["awaiting_booking_slot"] = True

    # -----------------------
    # Core message handler
    # -----------------------
    async def on_message_activity(self, turn_context: TurnContext):
        activity = turn_context.activity
        raw_in = (activity.text or "").strip()
        user_msg = raw_in
        if getattr(activity, "value", None):
            try:
                user_msg = str(activity.value)
            except Exception:
                user_msg = raw_in

        print(f"🗨️ User said: {user_msg}")

        # Emergency check
        if binary_emergency_check(user_msg):
            await self.send_and_log(turn_context, "🚨 This looks like an emergency. Please call your local emergency number immediately!")
            self.reset_state(hard_reset=True)
            
            return

        # Booking slot selection
        if self.state.get("awaiting_booking_slot"):
            raw = user_msg.strip()
            # check payload BOOK_SLOT:YYYY-MM-DD|HH:MM
            m = re.match(r"^BOOK_SLOT:(\d{4}-\d{2}-\d{2})\|(\d{2}:\d{2})$", raw)
            chosen_date = None
            chosen_time = None
            if m:
                chosen_date = m.group(1)
                chosen_time = m.group(2)
            else:
                # numeric 1/2/3 for time pick
                if re.fullmatch(r"\s*[1-3]\s*", raw):
                    idx = int(raw.strip())
                    try:
                        chosen_time = self.state["available_booking_slots"][idx-1][1]  # time_str
                        chosen_date = self.state.get("selected_booking_date")
                    except Exception:
                        chosen_time = None
                else:
                    # ISO time in text?
                    m2 = re.search(r"(\d{2}:\d{2})", raw)
                    if m2:
                        chosen_time = m2.group(1)
                        chosen_date = self.state.get("selected_booking_date")

            if chosen_date and chosen_time:
                # confirm booking
                self.state["booking_date"] = chosen_date
                self.state["booking_time"] = chosen_time
                self.state["intent"] = "BookAppointment"
                # clear booking flags
                self.state["awaiting_booking_slot"] = False
                self.state["awaiting_booking_date"] = False
                self.state["awaiting_post_summary"] = False
                await self.handle_final_intents(turn_context)
                return
            else:
                await self.send_and_log(turn_context, "Please tap one of the time buttons (1/2/3) or type the time in HH:MM format.")
                return

        # Booking date selection
        if self.state.get("awaiting_booking_date"):
            raw = user_msg.strip()
            m = re.match(r"^DATE:(\d{4}-\d{2}-\d{2})$", raw)
            chosen_date = None
            if m:
                chosen_date = m.group(1)
            else:
                # numeric pick 1/2/3
                if re.fullmatch(r"\s*[1-3]\s*", raw):
                    idx = int(raw.strip())
                    try:
                        chosen_date = self.state["available_booking_dates"][idx-1][1]
                    except Exception:
                        chosen_date = None
                else:
                    # try iso date in text
                    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
                    if m2:
                        chosen_date = m2.group(1)

            if chosen_date:
                # show time slots for chosen date
                await self.present_time_slots_for_date(turn_context, chosen_date)
                return
            else:
                await self.send_and_log(turn_context, "Please tap one of the date buttons (1/2/3) or type the date in YYYY-MM-DD format.")
                return

        # Post-summary options
        if self.state.get("awaiting_post_summary"):
            raw_choice = (activity.value if getattr(activity, "value", None) else user_msg or "").strip()
            lc = raw_choice.lower()

            # Handle booking appointment
            if any(word in lc for word in ["yes", "book", "appointment"]):
                self.state["awaiting_post_summary"] = False
                await self.present_booking_dates(turn_context)
                return

            activity = Activity(
                type=ActivityTypes.message,
                text="Please tap the 'Book Appointment' button or type 'book'.",
                suggested_actions=SuggestedActions(
                    actions=[CardAction(type=ActionTypes.im_back, title="Book Appointment", value="book")]
                )
            )
            await turn_context.send_activity(activity)
            return

        # Normal onboarding and questionnaire flow

        if self.state["user_info"]["name"] is None:
            # Try to capture full name from patterns
            match = re.search(r"(?:my name is|i am|i'm)\s+(.+)", user_msg, flags=re.I)
            if match:
                name = match.group(1).strip()   # keep full name
            else:
                # fallback: just take the whole input if no pattern matched
                name = user_msg.strip()

            self.state["user_info"]["name"] = name or "Patient"
            await self.send_and_log(
                turn_context,
                f"😊 Nice to meet you, {self.state['user_info']['name']}!\n"
                "Now, could you please tell me your age?"
            )
            return

        if self.state["user_info"]["age"] is None:
            # Try to extract a number (age) from input
            match = re.search(r"(\d{1,3})", user_msg)  # find any 1–3 digit number
            if match:
                age = match.group(1)   # just the number
            else:
                age = user_msg.strip() # fallback

            self.state["user_info"]["age"] = age
            await self.send_and_log(
                turn_context,
                f"✅ Thanks {self.state['user_info']['name']}. I have noted your age as {age}.\n"
                "Now, please describe your main symptom in a sentence."
            )
            return

        if not self.state["intent"]:
            result = analyze_and_respond(user_msg)
            intent = result.get("intent", "CheckSymptoms")
            entities = result.get("entities", {})
            reply = result.get("response", "❓ Sorry, I didn't understand.")
            
            # Add debug logging
            print(f"🔍 LLM Analysis: '{user_msg}' → Intent: {intent}, Entities: {entities}")

            allowed = {"Greeting", "CheckSymptoms", "BookAppointment", "CancelAppointment", "RescheduleAppointment", "Goodbye"}
            if intent not in allowed:
                intent = "OutOfScope"
                print(f"🔄 Intent changed to: {intent} (not in allowed list)")

            # Handle OutOfScope immediately
            if intent == "OutOfScope":
                print(f"🚫 Handling OutOfScope for: '{user_msg}'")
                await self.send_and_log(turn_context, "I'm a medical assistant focused on health symptoms and appointments. Is there anything health-related I can help you with?")
                # Don't set intent - keep it None so next message gets re-analyzed
                return

            # Set intent only for valid intents
            self.state["intent"] = intent
            self.state["entities"] = entities
            print(f"✅ Set intent to: {intent}")
            
            # Only send LLM reply for certain intents, not CheckSymptoms
            if intent not in ["CheckSymptoms"]:
                await self.send_and_log(turn_context, reply)

            if self.state["intent"] == "CheckSymptoms":
                await self.send_and_log(turn_context, "Thanks for sharing. Let's go through a quick symptom assessment.")
                await self.send_and_log(turn_context, "🩺 Let's do a short assessment about your daily activities.")
                await self.ask_next_question(turn_context)
                return
            elif self.state["intent"] in ["BookAppointment", "CancelAppointment", "RescheduleAppointment"]:
                await self.handle_final_intents(turn_context)
                return
            elif self.state["intent"] == "Goodbye":
                await self.send_and_log(turn_context, "👋 Take care and stay healthy!")
                self.reset_state(hard_reset=True)
                return

        if self.state["intent"] == "CheckSymptoms":
            q_index = self.state["q_index"]
            if q_index < len(QUESTIONS):
                digit = classify_answer_to_digit(user_msg)
                question_text = QUESTIONS[q_index]
                self.state["answers"][question_text] = digit
                print(f"📥 Recorded answer: Q{q_index+1}='{question_text}' -> {digit}")

            self.state["q_index"] += 1

            if self.state["q_index"] < len(QUESTIONS):
                await self.ask_next_question(turn_context)
            else:
                answers = self.state.get("answers", {})
                if not answers:
                    await self.send_and_log(turn_context, "No answers recorded.")
                else:
                    # Just show thank you message
                    await self.send_and_log(turn_context, "✨ Thank you for completing the assessment!\n")

                    # Continue with existing summary and recommendation
                    overall = max(answers.values())
                    label = INTENT_LABELS.get(overall, "Difficulty/Moderate")
                    consultant = CONSULTANT_MAP.get(overall, "Occupational Therapist")

                    data_for_summary = {
                        "user": self.state["user_info"],
                        "entities": self.state["entities"],
                        "answers": answers
                    }
                    summary_text = medical_summary(data_for_summary)

                    await self.send_and_log(turn_context, f"📝 Summary & Recommendation:\n\n{summary_text}")

                    post_text = (
                        f"Overall level: **{label.split('/')[-1]}**.\n"
                        f"Recommended specialist: **{consultant}**.\n\n"
                        "Would you like me to: Book an appointment\n"
                        "(Tap the button below)"
                    )

                    # Create activity with a single "Book Appointment" button
                    activity = Activity(
                        type=ActivityTypes.message,
                        text=post_text,
                        suggested_actions=SuggestedActions(
                            actions=[
                                CardAction(
                                    type=ActionTypes.im_back,
                                    title="Book Appointment",
                                    value="book"
                                )
                            ]
                        )
                    )
                    await turn_context.send_activity(activity)

                    # mark waiting for user's choice
                    self.state["awaiting_post_summary"] = True
                    self.state["intent"] = "PostSummaryOptions"
            return

        await self.send_and_log(turn_context, "Sorry — I didn't understand that. Could you rephrase?")

    async def ask_next_question(self, turn_context: TurnContext):
        q_index = self.state["q_index"]
        if q_index < len(QUESTIONS):
            question = f"**Question {q_index+1} of {len(QUESTIONS)}:** {QUESTIONS[q_index]}"
            
            # Create buttons 1-5
            actions = [
                CardAction(
                    type=ActionTypes.im_back,
                    title=str(i),
                    value=str(i)
                ) for i in range(1, 6)
            ]
            
            # Show options text with their meanings
            options_text = "\n".join(OPTIONS)
            
            # Create activity with question, options, and number buttons
            activity = Activity(
                type=ActivityTypes.message,
                text=f"{question}\n\n{options_text}\n\n(Tap a number button or type 1-5)",
                suggested_actions=SuggestedActions(actions=actions)
            )
            
            await turn_context.send_activity(activity)

    async def handle_final_intents(self, turn_context: TurnContext):
        # booking
        if self.state["intent"] == "BookAppointment":
            date_chosen = self.state.get("booking_date")
            time_chosen = self.state.get("booking_time")
            if date_chosen and time_chosen:
                friendly_time = None
                for label, ts in default_time_slots():
                    if ts == time_chosen:
                        friendly_time = label
                        break
                friendly_time = friendly_time or time_chosen
                # First confirm the selected slot
                await self.send_and_log(turn_context, f"📅 You've selected an appointment for {date_chosen} at {friendly_time}.")
                # Then show payment URL to confirm booking
                await self.send_and_log(turn_context, "Pay and confirm slot: [Click here](https://your-booking-url.com)")
            else:
                await self.send_and_log(turn_context, "📅 Please select an appointment time.")
        elif self.state["intent"] == "CancelAppointment":
            await self.send_and_log(turn_context, "❌ Your appointment has been cancelled. Thank you!")
        elif self.state["intent"] == "RescheduleAppointment":
            await self.send_and_log(turn_context, "🔄 Your appointment has been rescheduled. Thank you!")

        self.reset_state(hard_reset=True)

    def reset_state(self, hard_reset=False):
        self.state["intent"] = None
        self.state["entities"] = {}
        self.state["q_index"] = 0
        self.state["answers"] = {}
        self.state["awaiting_post_summary"] = False
        self.state["awaiting_booking_date"] = False
        self.state["awaiting_booking_slot"] = False
        self.state["available_booking_dates"] = []
        self.state["available_booking_slots"] = []
        self.state["selected_booking_date"] = None
        self.state["booking_date"] = None
        self.state["booking_time"] = None
        if hard_reset:
            self.state["user_info"] = {"name": None, "age": None}
            self.greeted = False

# ---------- Web server + adapter setup ----------
adapter_settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(adapter_settings)

memory = MemoryStorage()
conversation_state = ConversationState(memory)
bot = MedicalBot(conversation_state)

async def on_turn(turn_context: TurnContext):
    # Log user message if it's a message activity
    if turn_context.activity.type == "message":
        session_id = turn_context.activity.conversation.id
        user_msg = turn_context.activity.text
        log_message(session_id, "user", user_msg)

    await bot.on_turn(turn_context)
    await conversation_state.save_changes(turn_context)

async def messages(req: web.Request) -> web.Response:
    try:
        auth_header = req.headers.get("Authorization", "")
        response = await adapter.process_activity(req, auth_header, on_turn)
        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)
    except Exception as e:
        print("❌ Error in /api/messages:", str(e))
        traceback.print_exc()
        return web.Response(text=f"Error: {str(e)}", status=500)

# ---------- Run ----------
app = web.Application()
app.router.add_post("/api/messages", messages)

if __name__ == "__main__":
    print("Starting MedicalBot on http://localhost:3978/api/messages")
    web.run_app(app, host="localhost", port=3978)

