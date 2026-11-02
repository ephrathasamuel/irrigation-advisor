"""Start the app: python run.py, then open http://127.0.0.1:5000"""

import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402  (load .env before the app reads it)

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
