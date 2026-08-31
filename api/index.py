"""Vercel entry point — exposes the Flask app as the WSGI `app` Vercel expects."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "webapp"))
from app import app  # noqa: E402,F401
