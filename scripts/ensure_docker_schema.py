#!/usr/bin/env python3
"""
Ensure Docker settings document exists.
This script is safe to run on startup and is idempotent.
"""
import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models.settings import DockerSettings

app = create_app()

with app.app_context():
    try:
        # This will create the default config if it doesn't exist
        config = DockerSettings.get_config()
        print(f"Docker settings check complete. ID: {config.id}")
    except Exception as e:
        print(f"Failed to ensure docker schema: {e}")
        sys.exit(1)
