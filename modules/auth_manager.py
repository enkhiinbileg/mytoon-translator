import logging
import os
import json
from supabase import create_client, Client
from modules.utils.paths import get_user_data_dir

logger = logging.getLogger(__name__)

SUPABASE_URL = "https://jtlwllzaxscxqtcoqpll.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imp0bHdsbHpheHNjeHF0Y29xcGxsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njg0NjMxNzAsImV4cCI6MjA4NDAzOTE3MH0.e31jvTn1pD9bVRrR7q99EUvHiVDXD_xvhDUPKuwWwLo"

class AuthManager:
    def __init__(self):
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.auth_file = os.path.join(get_user_data_dir(), "auth_state.json")

    def get_saved_email(self):
        try:
            if os.path.exists(self.auth_file):
                with open(self.auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("email", "")
        except Exception as e:
            logger.error(f"Failed to read auth file: {e}")
        return ""

    def save_email(self, email):
        print(f"DEBUG: Saving email to JSON file: {email}")
        try:
            os.makedirs(os.path.dirname(self.auth_file), exist_ok=True)
            with open(self.auth_file, "w", encoding="utf-8") as f:
                json.dump({"email": email}, f)
        except Exception as e:
            logger.error(f"Failed to save auth file: {e}")

    def check_access(self, email: str = None) -> bool:
        """Checks if the given email (or saved email) has app access."""
        target_email = email or self.get_saved_email()
        if not target_email:
            return False
            
        try:
            # Call the RPC function we created in Supabase
            response = self.supabase.rpc("check_app_access", {"user_email": target_email.strip().lower()}).execute()
            is_valid = bool(response.data)
            print(f"DEBUG: Auth check for {target_email}: {'AUTHORIZED' if is_valid else 'DENIED'}")
            
            # ONLY logout if the server explicitly returned False (not None or error)
            if response.data is False and not email:
                self.logout()
            return is_valid
        except Exception as e:
            logger.error(f"Error checking access: {e}")
            # In case of network error, we might want to allow temporary offline use
            # or strictly block. Let's block for now to be safe.
            return False

    def logout(self):
        try:
            if os.path.exists(self.auth_file):
                os.remove(self.auth_file)
        except Exception as e:
            logger.error(f"Failed to clear auth file: {e}")
