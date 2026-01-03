#!/usr/bin/env python3
"""
Test script to save conversations for an existing session.
"""
from scripts.finalize_user import save_conversations_to_postgres
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test with Ananya's session
session_id = "76d894a4-f9fd-48ea-9a97-ed36d69ca576"
user_id = 4  # Ananya's user_id in Postgres

print(f"🔄 Testing conversation save for session {session_id}, user_id {user_id}")

result = save_conversations_to_postgres(session_id, user_id)

if result:
    print(f"✅ Successfully saved conversations!")
else:
    print(f"❌ Failed to save conversations")
