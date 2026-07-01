"""End-to-end check for POST /submit and GET /log, via Flask's test client.

Uses app.app.test_client() so there is no port to fight with (localhost:5000
clashes with macOS AirPlay). Submits a clearly human and a clearly AI sample,
shows that the combined scores are noticeably different, then reads GET /log to
confirm each entry records BOTH signals individually and the combined result.

Calls the Groq API (Signal 1), so it needs GROQ_API_KEY and spends a couple
requests of quota.

Run from the project root:
    .venv/bin/python tests/verify_submit.py
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

import app as app_module  # noqa: E402

client = app_module.app.test_client()

SAMPLES = [
    (
        "clearly human",
        "human-demo",
        "ok so i finally tried that new ramen place downtown and honestly? "
        "underwhelming. the broth was fine but they put WAY too much sodium in it "
        "and i was thirsty for like three hours after. my friend got the spicy "
        "version and said it was better. probably won't go back unless someone "
        "drags me there",
    ),
    (
        "clearly AI",
        "ai-demo",
        "Our team is committed to delivering excellent results. Our team is focused "
        "on meeting every client need. Our team is dedicated to maintaining the "
        "highest standards. Our team is working hard to exceed all expectations. "
        "Our team is proud to support our valued customers. Our team is ready to "
        "tackle any new challenge. Our team is eager to build lasting business "
        "relationships. Our team is passionate about continuous learning and steady "
        "growth. Our team is confident in our long and proven track record. Our "
        "team is here to provide reliable ongoing support.",
    ),
]


def main():
    print("########## POST /submit ##########\n")
    for name, creator_id, text in SAMPLES:
        resp = client.post("/submit", json={"text": text, "creator_id": creator_id})
        body = resp.get_json()
        print(f"=== {name} (HTTP {resp.status_code}) ===")
        print(f"  attribution : {body['attribution']}")
        print(f"  confidence  : {body['confidence']}")
        print(f"  signals     : {json.dumps(body['signals'])}")
        print(f"  content_id  : {body['content_id']}")
        print()

    print("########## GET /log?limit=2 (newest first) ##########\n")
    resp = client.get("/log?limit=2")
    log = resp.get_json()
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
