import os
import json
import psycopg2
from datetime import datetime
from socmint_service import SocmintService

def test_save_socmint_data():
    # Setup test data
    user_id = 1  # Make sure this user exists in your users table
    platform = 'instagram'
    username = 'testuser'
    data = {'bio': 'Test bio', 'followers': 123}

    service = SocmintService()
    try:
        new_id = service.save_socmint_data(user_id, platform, username, data)
        print(f"Inserted socmint_profiles row with id: {new_id}")
    except Exception as e:
        print(f"Error inserting socmint_profiles row: {e}")

if __name__ == "__main__":
    test_save_socmint_data()
