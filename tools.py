import requests
import datetime
import json, uuid
from langchain_core.tools import tool
from redis_client import r
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database.models import User
from database.db import SessionLocal
from dotenv import load_dotenv
import os
import secrets
import smtplib
from dateutil import parser
from email.message import EmailMessage
from email_validator import validate_email, EmailNotValidError

load_dotenv()  # loads the .env file
TTL_SECONDS = 3600  # 1 hour, so temp signup sessions auto-expire
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# ========================================
# UNIFIED SESSION HELPERS
# ========================================
def get_session_data(session_id: str) -> dict:
    """
    Safely retrieves the ENTIRE session from Redis.
    Structure: {"messages": [...], "signup_data": {...}}
    """
    data = r.get(f"session:{session_id}")
    if data:
        session = json.loads(data)
        code = session.get("signup_data", {}).get("verificationCodeGenerated")
        if code:
            print(f"📖 LOAD: session:{session_id} - Code={code}")
        return session
    else:
        # Return default structure
        print(f"📖 LOAD: session:{session_id} - NEW SESSION (no data)")
        return {
            "messages": [],
            "signup_data": {}
        }

def save_session_data(session_id: str, session_data: dict):
    """Save the entire session back to Redis."""
    # DEBUG: Log verification code changes
    code = session_data.get("signup_data", {}).get("verificationCodeGenerated")
    if code is not None:
        print(f"💾 SAVE: session:{session_id} - Code={code}")
    r.setex(f"session:{session_id}", 1800, json.dumps(session_data))

def get_signup_data(session_id: str) -> dict:
    """Extract just the signup_data portion."""
    session = get_session_data(session_id)
    return session.get("signup_data", {})



#If user is trying to sign up. 
@tool
def create_redis_session(session_id: str) -> str:
    """If the user chooses to sign up, call this method with the session_id from the frontend. 
    It initializes a signup data object in Redis under the given session_id,
    allowing user signup information to be collected and stored throughout the flow."""
    # Get existing session (might already have messages from the conversation)
    session_data = get_session_data(session_id)
    
    existing_code = session_data.get("signup_data", {}).get("verificationCodeGenerated")
    if existing_code:
        print(f"\n⚠️  create_redis_session called but code {existing_code} already exists - NOT wiping data\n")
    
    # Initialize signup_data if not present
    if not session_data.get("signup_data"):
        session_data["signup_data"] = {}
        print(f"\n✅ create_redis_session: Initialized empty signup_data for {session_id}\n")
    else:
        print(f"\n✅ create_redis_session: signup_data already exists, keeping it\n")
    
    # Save back to Redis
    save_session_data(session_id, session_data)
    return f"Signup session initialized for {session_id}"

@tool
def set_username(session_id: str, username: str) -> str:
    """The tool for getting + storing the username for the user, should they want to sign up.
    We use the session_id to access the user's temporary object stored in Redis, 
    and we get the username from the user input after being prompted by the bot.
    Returns a string 'Username {username} saved!' if the username gets saved."""
    session_data = get_session_data(session_id)
    session_data["signup_data"]["username"] = username
    save_session_data(session_id, session_data)
    return f"Username {username} saved!"

@tool 
def set_password(session_id: str, password: str) -> str:
    """The tool for setting the desired password for the user, should they want to sign up.
    We use the session_id to access the user's temporary object stored in Redis, 
    and we get the username from the user input after being prompted by the bot.
    Returns a string 'Password saved!' if the password gets saved."""
    session_data = get_session_data(session_id)
    session_data["signup_data"]["desiredPassword"] = password  # Store the plain password first
    session_data["signup_data"]["password"] = generate_password_hash(password)  # Store the hashed version
    save_session_data(session_id, session_data)
    return f"Password saved!"

@tool 
def confirm_password(session_id: str, confirmPassword: str) -> bool:
    """
    Checks whether the confirmPassword matches the password previously entered
    and stored in the user's Redis session. 
    Returns:
        True  -> if the passwords match
        False -> if they do not match
    """
    session_data = get_session_data(session_id)
    signup_data = session_data.get("signup_data", {})

    # check if a password was already stored
    if "desiredPassword" not in signup_data:
        return "No password found. Please enter your password first."

    # compare the confirmPassword with the stored one
    if signup_data["desiredPassword"] == confirmPassword:
        session_data["signup_data"]["confirmPassword"] = confirmPassword
        save_session_data(session_id, session_data)
        return True
    else:
        return False


@tool
def get_email(session_id: str, email: str) -> str:
    """
    Gets the user's email. 

    Uses the session_id to access the user's temporary object stored in Redis, 
    and the email from the user input after being prompted by the bot.

    Returns:
    str: 
    - "That doesn't look like a valid email. Try again?" if the email is invalid.
    - "Email {normalized_email} saved!" if the email is valid.
    """

    try:
        valid = validate_email(email)
        normalized_email = valid.email
    except EmailNotValidError:
        return "That doesn't look like a valid email. Try again?"

    session_data = get_session_data(session_id)
    session_data["signup_data"]["email"] = normalized_email
    save_session_data(session_id, session_data)

    return f"Email {normalized_email} saved!"

@tool
def get_user_birthday(session_id: str, birthday: str) -> str:
    """
    Stores the user's birthday in Redis.
    Accepts flexible formats (e.g. '2003-07-12', 'July 12 2003', '7/12/03', etc.).
    Returns a string "couldn't read that date 😭 try something like 2003-07-12 or July 12, 2003." if the user input is not a compatible date. 
    Returns a string "birthday {birthday_date.strftime('%B %d, %Y')} saved! 🎂" if the user input is in a compatible date format. 
    """
    try:
        birthday_date = parser.parse(birthday, fuzzy=True)
    except Exception:
        return "couldn't read that date 😭 try something like 2003-07-12 or July 12, 2003."

    session_data = get_session_data(session_id)
    session_data["signup_data"]["birthday"] = birthday_date.date().isoformat()
    save_session_data(session_id, session_data)

    return f"birthday {birthday_date.strftime('%B %d, %Y')} saved! 🎂"


@tool 
def get_user_gender(session_id: str, gender: str) -> str:
    """
    Stores the user's gender in Redis for the signup flow. Make sure they enter a valid gender. 
    Returns "Gender '{gender}' saved!" if the gender gets saved successfully. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["gender"] = gender
    save_session_data(session_id, session_data)
    return f"Gender '{gender}' saved!"


@tool 
def get_user_sexuality(session_id: str, sexuality: str) -> str:
    """
    Stores the user's sexuality in Redis during the signup flow.
    The sexuality input (e.g. 'straight', 'gay', 'bisexual', etc.)
    is saved to the user's temporary signup object.
    Returns the string: "Sexuality '{sexuality}' saved!" when it gets saved successfully. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["sexuality"] = sexuality.strip().lower()  # normalize input
    save_session_data(session_id, session_data)
    return f"Sexuality '{sexuality}' saved!"  


@tool 
def get_user_ethnicity(session_id: str, ethnicity: str) -> str:
    """
    Stores the user's ethnicity in Redis during the signup flow.
    The ethnicity input (e.g. 'South Asian', 'Latina', 'White', etc.)
    is saved to the user's temporary signup object.
    Returns the string "Ethnicity '{ethnicity}' saved!" when the ethnicity gets successfully saved. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["ethnicity"] = ethnicity.strip().title()  # clean + normalize formatting
    save_session_data(session_id, session_data)
    return f"Ethnicity '{ethnicity}' saved!"


@tool 
def get_user_pronouns(session_id: str, pronouns: str) -> str:
    """
    Stores the user's pronouns in Redis during the signup flow.
    Example inputs: 'she/her', 'he/him', 'they/them', etc.
    Returns the string "Pronouns '{pronouns}' saved!" when the pronounds get saved. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["pronouns"] = pronouns.strip().lower()
    save_session_data(session_id, session_data)
    return f"Pronouns '{pronouns}' saved!"


@tool 
def get_user_first_name(session_id: str, first_name: str) -> str:
    """
    Stores the user's first name in Redis during the signup flow.
    Example input: 'Archita'
    Returns the string "First name '{first_name}' saved!" when the first name gets saved successfully. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["name"] = first_name.strip().title()  # normalize name
    save_session_data(session_id, session_data)
    return f"First name '{first_name}' saved!"


@tool 
def get_user_university(session_id: str, university: str) -> str:
    """
    Stores the user's university in Redis during the signup flow.
    Example input: 'Cornell University'
    Returns "University '{university}' saved!" when the university gets successfully saved. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["university"] = university.strip().title()  # normalize formatting
    save_session_data(session_id, session_data)
    return f"University '{university}' saved!"

@tool 
def get_user_occupation(session_id: str, occupation: str) -> str:
    """
    Stores the user's occupation or career field in Redis during the signup flow.
    Example input: 'Software Engineer' or 'Investment Banking Summer Analyst'
    Returns "Occupation '{occupation}' saved!" when the occupation gets successfully saved. 
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["occupation"] = occupation.strip().title()  # normalize formatting
    save_session_data(session_id, session_data)
    return f"Occupation '{occupation}' saved!"

@tool 
def get_user_college_major(session_id: str, college_major: str):
    """
    Stores the user's college major in Redis during the signup flow.
    Example input: 'Electrical and Computer Engineering' 
    Returns "College major '{college_major}' saved!" when the college major gets successfully saved.
    """
    session_data = get_session_data(session_id)
    session_data["signup_data"]["college_major"] = college_major.strip().title()  # normalize formatting
    save_session_data(session_id, session_data)
    return f"College major '{college_major}' saved!"

# ========================================
# NOTE: store_user_sentence and store_assistant_sentence have been REMOVED
# Conversations are now automatically saved in the unified session structure
# by app.py's save_session() function. No need for separate tools.
# ========================================

@tool
def generate_verification_code(session_id: str) -> str:
    """
    Send a verification code to the user's email. 
    Only call this ONCE when the user first asks for a code.
    DO NOT call this again when the user is providing their code to verify!
    Returns the string "verification code '{verification_code}' saved!" if the verification code is successfully sent and saved. 
    """
    session_data = get_session_data(session_id)
    signup_data = session_data.get("signup_data", {})
    email = signup_data.get("email")

    # Check if required fields are present
    required_fields = {
        "name": "first name",
        "username": "username",
        "password": "password",
        "email": "email"
    }

    missing_fields = []
    for field, display_name in required_fields.items():
        if not signup_data.get(field):
            missing_fields.append(display_name)

    if missing_fields:
        return f"Cannot send verification code yet. Missing required fields: {', '.join(missing_fields)}. Please collect these first."

    # Check if a code already exists
    existing_code = signup_data.get("verificationCodeGenerated")
    if existing_code is not None:
        print(f"\n⚠️  WARNING: Verification code already exists: {existing_code}")
        print(f"   NOT generating a new code. Tell user to check their email for the existing code.\n")
        return f"A verification code was already sent to {email}. Please check your email!"

    #generate a verification code and send it to that email. 
    verification_code = secrets.randbelow(900000) + 100000
    session_data["signup_data"]["verificationCodeGenerated"] = verification_code
    save_session_data(session_id, session_data)

    # DEBUG: Print what we stored
    print(f"\n📧 DEBUG GENERATE CODE:")
    print(f"  Session ID: {session_id}")
    print(f"  Generated code: {verification_code} (type: {type(verification_code)})")
    print(f"  Sending to email: {email}\n")

    #send code via email
    subject = "hey bestie 💌 "
    body = f"bestieee ur Glow verification code is {verification_code}. now hurry before the universe catches on ur new era! <3"

    try:
        send_email(email, body, subject)
        return f"verification code sent to {email}!"
    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        return f"Sorry, I couldn't send the email right now. Please check your email configuration. Error: {str(e)}"

@tool
def resend_verification_code(session_id: str) -> str:
    """
    Resend a NEW verification code to the user's email.
    Only call this if the user explicitly asks for a new code or to resend.
    This will generate a NEW code and overwrite the old one.
    """
    session_data = get_session_data(session_id)
    signup_data = session_data.get("signup_data", {})
    email = signup_data.get("email")
    
    # Generate NEW code
    verification_code = secrets.randbelow(900000) + 100000
    session_data["signup_data"]["verificationCodeGenerated"] = verification_code
    save_session_data(session_id, session_data)
    
    print(f"\n🔄 RESENDING NEW CODE:")
    print(f"  Session ID: {session_id}")
    print(f"  New code: {verification_code}")
    print(f"  Sending to email: {email}\n")
    
    # Send new code via email
    subject = "hey bestie 💌 "
    body = f"here's your new Glow verification code: {verification_code}. the old one won't work anymore!"

    try:
        send_email(email, body, subject)
        return f"New verification code sent to {email}!"
    except Exception as e:
        print(f"❌ Email sending failed: {e}")
        return f"Sorry, I couldn't send the email right now. Please check your email configuration. Error: {str(e)}"

def is_valid_email(email):
    try:
        # validate and normalize the email
        valid = validate_email(email)
        return valid.email  # returns normalized email (e.g. lowercase)
    except EmailNotValidError as e:
        return None  # invalid email


def send_email(to_email, body, subject="hey bestie 💌"):
    # create email object
    msg = EmailMessage()
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    # connect to Gmail’s SMTP server
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)


@tool
def log_in_user() -> str:
    """Get the user logged in."""
    return "logging you in bestie"


# ========================================
# LOGIN SYSTEM TOOLS
# ========================================

@tool
def switch_to_login_mode(session_id: str) -> str:
    """
    Call this when user wants to log in instead of sign up.
    This switches the conversation to login mode.
    """
    session_data = get_session_data(session_id)
    session_data["is_login"] = True
    session_data["login_data"] = {}
    save_session_data(session_id, session_data)
    print(f"✅ Switched to login mode for session {session_id}")
    return "Switched to login mode. Now ask for their username or email."

@tool
def get_login_username(session_id: str, username: str) -> str:
    """
    Store the username or email for login.
    This is called after asking the user for their login credentials.

    Args:
        session_id: The session ID
        username: The username or email provided by the user
    """
    session_data = get_session_data(session_id)

    # Initialize login_data if not present
    if "login_data" not in session_data:
        session_data["login_data"] = {}

    session_data["login_data"]["username"] = username.strip()
    save_session_data(session_id, session_data)

    print(f"✅ Stored login username: {username}")
    return f"Username '{username}' saved. Now ask for their password."

@tool
def get_login_password(session_id: str, password: str) -> str:
    """
    Store the password for login (hashed immediately for security).
    This is called after asking the user for their password.

    Args:
        session_id: The session ID
        password: The password provided by the user
    """
    session_data = get_session_data(session_id)

    # Initialize login_data if not present
    if "login_data" not in session_data:
        session_data["login_data"] = {}

    # Store the plain password temporarily (will be verified against hash in DB)
    session_data["login_data"]["password"] = password
    save_session_data(session_id, session_data)

    print(f"✅ Stored login password")
    return "Password saved. Now verify the credentials."

@tool
def verify_login_credentials(session_id: str) -> str:
    """
    Verify the login credentials against the database.
    Checks if username/email exists and password matches.
    If successful, returns user info. If failed, returns error message.

    Args:
        session_id: The session ID containing login_data
    """
    session_data = get_session_data(session_id)
    login_data = session_data.get("login_data", {})

    username = login_data.get("username", "").strip()
    password = login_data.get("password", "")

    if not username or not password:
        return "Error: Missing username or password. Please provide both."

    # Query database
    db = SessionLocal()
    try:
        # Try to find user by username OR email
        user = db.query(User).filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user:
            print(f"❌ Login failed: User '{username}' not found")
            return "incorrect"

        # Check password
        if not check_password_hash(user.password, password):
            print(f"❌ Login failed: Invalid password for '{username}'")
            return "incorrect"

        # SUCCESS! Store user_id in session
        session_data["login_verified"] = True
        session_data["verified_user_id"] = user.id

        # Clear password from Redis for security
        session_data["login_data"]["password"] = "[REDACTED]"

        save_session_data(session_id, session_data)

        print(f"✅ Login successful for user {user.username} (ID: {user.id})")
        return "verified"

    except Exception as e:
        print(f"❌ Database error during login: {str(e)}")
        return f"Error during login verification: {str(e)}"
    finally:
        db.close()

@tool
def finalize_login(session_id: str) -> str:
    """
    Finalize the login process by generating JWT tokens and storing user_id in Redis.
    This is called after credentials are verified.
    Call this only after verify_login_credentials returns 'verified'.

    Args:
        session_id: The session ID
    """
    from jwt_utils import create_access_token, create_refresh_token

    session_data = get_session_data(session_id)

    # Check if login was verified
    if not session_data.get("login_verified"):
        return "Error: Login credentials not verified yet. Call verify_login_credentials first."

    user_id = session_data.get("verified_user_id")
    if not user_id:
        return "Error: No user_id found. Verification may have failed."

    try:
        # Generate JWT tokens
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)

        # Store in Redis session for polling
        session_data["user_id"] = user_id
        session_data["access_token"] = access_token
        session_data["refresh_token"] = refresh_token

        save_session_data(session_id, session_data)

        print(f"✅ Login finalized for user {user_id}")
        print(f"   Access token: {access_token[:20]}...")
        print(f"   Refresh token: {refresh_token[:20]}...")

        return "verified"

    except Exception as e:
        print(f"❌ Error finalizing login: {str(e)}")
        return f"Error finalizing login: {str(e)}"


#helper functions
def delete_redis_key(session_id: str) -> str:
    """
    This redis session_id of the onboarding conversation is deleted from redis.
    """
    if session_id:
        r.delete(f"session:{session_id}")
    else:
        return f"The session ID {session_id} has not been found."

    return f"the session ID had been successfully deleted from redis."



 