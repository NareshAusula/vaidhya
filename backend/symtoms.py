import os
import json
import traceback
import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from chat import init_db, log_message
init_db()

from dotenv import load_dotenv

load_dotenv()
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
    4: "Hand Surgeon + Occupational Therapist",
    5: "Urgent Hand Surgeon / Rheumatologist referral"
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
   - Greeting
   - CheckSymptoms
   - BookAppointment
   - CancelAppointment
   - RescheduleAppointment
   - Goodbye
   - OutOfScope
2. If input describes a health issue → CheckSymptoms.
3. Booking → BookAppointment.
4. Cancel → CancelAppointment.
5. Reschedule → RescheduleAppointment.
6. Hi/hello → Greeting.
7. Bye → Goodbye.
8. Anything unrelated → OutOfScope.
9. Extract entities if present: symptom, date, time, relative_date.
10. Generate a natural response string.

Return JSON only. Example:
{{"intent":"Greeting", "entities": {{"symptom": null, "date": null, "time": null, "relative_date": null}}, "response":"Hi! ..."}}

User: "{user_input}"
"""
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        return json.loads(text)
    except Exception:
        return {
            "intent": "CheckSymptoms",
            "entities": {"symptom": user_input, "date": None, "time": None, "relative_date": None},
            "response": "Thanks for sharing. Let’s go through a quick symptom assessment."
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
- Always prioritize the patient's main symptom (entities.symptom).
- Questionnaire answers are supportive context only.
- Provide:
  1. Possible medical condition (short, in medical terms)
  2. Which specialist doctor to consult
- End with: "⚠️ This is not a medical diagnosis. Please consult a doctor."
"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        return (
            "Based on the symptoms and questionnaire, I recommend seeing a specialist.\n"
            "Next steps: please consult a doctor for a formal diagnosis. ⚠️ This is not a medical diagnosis. Please consult a doctor."
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
        actions = []
        for idx, (label, iso_date) in enumerate(dates, start=1):
            title = f"Date {idx}: {label}"
            actions.append(CardAction(type=ActionTypes.im_back, title=title, value=str(idx)))

        suggested = SuggestedActions(actions=actions)
        text_lines = ["Please pick a date for your appointment (tap a button or type 1/2/3):"]
        for i, (label, iso_date) in enumerate(dates, start=1):
            text_lines.append(f"{i}) {label} — {iso_date}")
        message_text = "\n".join(text_lines)
        # Add the Pay and Book appointment URL below the options
        # message_text += "\n\nPay and Book appointment: [Click here](https://your-booking-url.com)"
        await self.send_and_log(turn_context, message_text)
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
        user_msg = (activity.text or "").strip()

        # Handle post-summary booking option
        if self.state.get("awaiting_post_summary"):
            # Fix: Safely handle None values
            raw_choice = ""
            if hasattr(activity, "value") and activity.value is not None:
                raw_choice = str(activity.value)
            elif user_msg:
                raw_choice = user_msg
            
            # Check if user wants to book (either clicked button or typed)
            if raw_choice.lower() in ["book", "book appointment", "1"] or "book" in raw_choice.lower():
                self.state["awaiting_post_summary"] = False
                self.state["intent"] = "BookAppointment"
                # Present booking dates
                await self.present_booking_dates(turn_context)
                return
            else:
                await self.send_and_log(turn_context, "Please tap the 'Book Appointment' button or type 'book'.")
                return
            
        # Handle date selection
        if self.state.get("awaiting_booking_date"):
            raw = user_msg.strip()
            if re.fullmatch(r"\s*[1-3]\s*", raw):
                idx = int(raw.strip()) - 1
                try:
                    chosen_date = self.state["available_booking_dates"][idx][1]  # Get ISO date
                    await self.present_time_slots_for_date(turn_context, chosen_date)
                    return
                except IndexError:
                    await self.send_and_log(turn_context, "Please choose a valid date (1-3).")
                    return
            else:
                await self.send_and_log(turn_context, "Please tap one of the date buttons or type 1, 2, or 3.")
                return

        # Handle time slot selection
        if self.state.get("awaiting_booking_slot"):
            raw = user_msg.strip()
            if re.fullmatch(r"\s*[1-3]\s*", raw):
                idx = int(raw.strip()) - 1
                try:
                    chosen_time = self.state["available_booking_slots"][idx][1]  # Get time value
                    chosen_date = self.state["selected_booking_date"]
                    if chosen_date and chosen_time:
                        self.state["booking_date"] = chosen_date
                        self.state["booking_time"] = chosen_time
                        await self.handle_final_intents(turn_context)
                        return
                except IndexError:
                    pass
            await self.send_and_log(turn_context, "Please tap one of the time buttons or type 1, 2, or 3.")
            return

        # Name capture
        if self.state["user_info"]["name"] is None:
            match = re.search(r"(?:my name is|i am|i'm)\s+(.+)", user_msg, flags=re.I)
            name = match.group(1).strip() if match else user_msg.strip()
            self.state["user_info"]["name"] = name or "Patient"
            await self.send_and_log(
                turn_context,
                f"😊 Nice to meet you, {self.state['user_info']['name']}!\n"
                "Now, could you please tell me your age?"
            )
            return

        # Age capture
        if self.state["user_info"]["age"] is None:
            match = re.search(r"(\d{1,3})", user_msg)
            age = match.group(1) if match else user_msg.strip()
            self.state["user_info"]["age"] = age
            await self.send_and_log(
                turn_context,
                f"✅ Thanks {self.state['user_info']['name']}. I have noted your age as {age}.\n"
                "Please fill out this short assessment form about your daily activities."
            )
            # Start questionnaire immediately
            self.state["intent"] = "CheckSymptoms"
            await self.ask_next_question(turn_context)
            return

        # Handle questionnaire
        if self.state["intent"] == "CheckSymptoms":
            q_index = self.state["q_index"]
            if q_index < len(QUESTIONS):
                digit = classify_answer_to_digit(user_msg)
                self.state["answers"][QUESTIONS[q_index]] = digit

            self.state["q_index"] += 1

            if self.state["q_index"] < len(QUESTIONS):
                await self.ask_next_question(turn_context)
            else:
                # Questionnaire completed
                await self.send_and_log(turn_context, "✨ Thank you for completing the assessment!\n")

                # Generate summary
                answers = self.state.get("answers", {})
                overall = max(answers.values())
                label = INTENT_LABELS.get(overall, "Difficulty/Moderate")
                consultant = CONSULTANT_MAP.get(overall, "Occupational Therapist")

                summary_text = medical_summary({
                    "user": self.state["user_info"],
                    "entities": {},  # Empty since we're not collecting symptoms
                    "answers": answers
                })

                await self.send_and_log(turn_context, f"📝 Summary & Recommendation:\n\n{summary_text}")

                # Offer booking
                post_text = (
                    f"Overall level: **{label.split('/')[-1]}**.\n"
                    f"Recommended specialist: **{consultant}**.\n\n"
                    "Would you like me to: Book an appointment\n"
                    "(Tap the button below)"
                )

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
                self.state["awaiting_post_summary"] = True
                return

        # Rest of the code (booking flow) remains the same
        # ...existing code for handling booking...

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

