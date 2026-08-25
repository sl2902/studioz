"""
Save a completed job's result as the golden demo file.

Usage:
    python -m studioz.save_demo_result <job_id>

This calls the running server's POST /api/demo/save/{job_id} endpoint,
which has direct access to the in-memory JOBS store. The server must be
running for this to work.

Alternatively, use curl directly:
    curl -X POST http://localhost:8000/api/demo/save/<job_id>

Or use the Swagger UI at http://localhost:8000/docs
"""

import sys
import urllib.request
import urllib.error
import json


SERVER_URL = "http://localhost:8000"


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m studioz.save_demo_result <job_id>")
        print(f"\nThis calls POST {SERVER_URL}/api/demo/save/<job_id>")
        print("The FastAPI server must be running.")
        return

    job_id = sys.argv[1]
    url = f"{SERVER_URL}/api/demo/set-golden/{job_id}"

    print(f"Setting golden demo via: POST {url}")
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            print(f"  Saved successfully!")
            print(f"  Title: {data.get('title', 'Unknown')}")
            print(f"  Path: {data.get('path')}")
            print(f"  Storyboard: {'yes' if data.get('has_storyboard') else 'no'}")
            print(f"  Video: {'yes' if data.get('has_video') else 'no'}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        print(f"  Error ({e.code}): {detail}")
    except urllib.error.URLError as e:
        print(f"  Cannot connect to server at {SERVER_URL}")
        print(f"  Make sure the FastAPI server is running: uvicorn studioz.api.main:app --port 8000")
        print(f"  Error: {e.reason}")


if __name__ == "__main__":
    main()
