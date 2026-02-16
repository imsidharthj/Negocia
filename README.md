# Negocia — Omi Integration Backend

Real-time sales negotiation insights powered by [Omi AI](https://www.omi.me/) transcription.

## Overview

Negocia receives live transcription data from Omi via webhooks, processes sales conversations in real time, and exposes structured insights (objections, buying signals, competitor mentions, next steps) through REST APIs.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Server:** Uvicorn
- **Storage:** In-memory / Redis
- **Deployment:** Render / Railway / Fly.io (public HTTPS)

## Quickstart

```bash
# 1. Clone & enter the project
git clone <repo-url> && cd Negocia

# 2. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy env config
cp .env.example .env

# 5. Run the dev server
uvicorn app.main:app --reload

# 6. Verify
curl http://localhost:8000/health
```

## API Endpoints

| Method | Path           | Description                        |
|--------|----------------|------------------------------------|
| GET    | `/health`      | Service health check               |
| POST   | `/omi/webhook` | Receive Omi transcription events   |
| GET    | `/insights/{session_id}` | Retrieve insights for a session |

## Project Structure

```
Negocia/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app factory
│   ├── config.py        # Pydantic BaseSettings
│   └── api/
│       ├── __init__.py
│       └── health.py    # Health check endpoint
├── requirements.txt
├── .env.example
└── README.md
```

## License

See [LICENSE](LICENSE).
