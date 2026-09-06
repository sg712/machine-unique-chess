"""Render fixtures for DOM tests, with no server or production connection."""
import json
import os
from pathlib import Path
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='muc-dom-fixtures-') as tmp:
    os.environ.pop('DATABASE_URL', None)
    os.environ['DB_PATH'] = str(Path(tmp) / 'test.db')
    os.environ['SECRET_KEY'] = 'fixture-only'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
    import app as site
    client = site.app.test_client()
    target = client.get('/test?new=1').location
    pages = {route: client.get(route).get_data(as_text=True)
             for route in ['/', '/learn', '/pattern/0', '/pattern/0/drill', '/test', '/register', '/research']}
    pages['quiz'] = client.get(target).get_data(as_text=True)
    pages['quiz_url'] = target
    print(json.dumps(pages))
