"""Force mock mode for the whole test session BEFORE any app import.

A parent `.env` may set MYSQL_HOST / LLM creds; setting these to empty strings
here (load_dotenv uses override=False) keeps tests on MockLLM + MockConfigStore
and never touches the real DB or an LLM provider.
"""
import os

os.environ["USE_REAL_LLM"] = ""
os.environ["MYSQL_HOST"] = ""
