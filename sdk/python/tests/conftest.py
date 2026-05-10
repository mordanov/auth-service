"""Test configuration for auth_client SDK tests."""
import sys
import os

# Ensure auth_client is importable from the sdk/python directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
