#!/usr/bin/env python3
"""Test database connection"""
import os
from dotenv import load_dotenv
from chat import init_db, log_message, get_session_logs

# Load environment variables
load_dotenv()

def test_connection():
    try:
        print("🔄 Testing database connection...")
        
        # Initialize database (create tables if needed)
        init_db()
        print("✅ Database initialized successfully!")
        
        # Test logging a message
        test_session = "test_session_123"
        log_message(test_session, "user", "Hello, this is a test message!")
        log_message(test_session, "bot", "Hi! I received your test message.")
        print("✅ Messages logged successfully!")
        
        # Test retrieving messages
        logs = get_session_logs(test_session)
        print(f"✅ Retrieved {len(logs)} messages from database:")
        for sender, message, timestamp in logs:
            print(f"  {sender}: {message} (at {timestamp})")
            
        print("\n🎉 Database connection test PASSED!")
        
    except Exception as e:
        print(f"❌ Database connection test FAILED: {e}")

if __name__ == "__main__":
    test_connection()