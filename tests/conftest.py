"""
Pytest configuration — ensures test environment is properly set up.

Sets DEV_AUTH_BYPASS and SERVER_DEBUG so that auth module can be imported
without a real Firebase service account file.
"""
import os
import sys

# Ensure project root is on sys.path for `import auth`, `import server`, etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dev-mode env defaults for testing (auth bypass on loopback)
os.environ.setdefault("SERVER_DEBUG", "true")
os.environ.setdefault("SERVER_HOST", "127.0.0.1")
os.environ.setdefault("DEV_AUTH_BYPASS", "true")
