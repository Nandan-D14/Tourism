# Tourist Place Finder Agent

A production-minded Google ADK + FastAPI project that recommends five tourist places, builds a realistic one-day itinerary, and is ready to containerize for GCP Cloud Run.

## Project Structure

- `backend/`: ADK app, FastAPI API, Docker assets, and environment templates.
- `frontend/`: single-file hackathon frontend with no build step.

## Prerequisites

- Python 3.11 or newer
- A valid backend API key configured in `backend/.env`
- Google Cloud SDK if you want to deploy with `gcloud`: https://cloud.google.com/sdk/docs/install
- Docker Desktop if you want to build and test the container locally

## Security Notes

- Keep real credentials only in `backend/.env`, Secret Manager, or your shell environment.
- Do not commit `.env`, service account JSON files, or private keys.
- Cloud Run source deploys from `backend/` now use `backend/.gcloudignore` and `backend/.dockerignore` so local secrets and caches stay out of the uploaded source and image layers.

# Local Run
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Add your backend API key
uvicorn main:app --reload --port 8000
# Open frontend/index.html in browser

# Test with curl
curl -X POST http://localhost:8000/find-places \
  -H "Content-Type: application/json" \
  -d '{"city": "Shimoga", "interest": "waterfalls"}'

# ADK Dev UI (bonus - great for hackathon demo)
cd backend && adk web

## API Endpoints

- `GET /health`: basic health response for the FastAPI wrapper.
- `POST /find-places`: takes `{ "city": "...", "interest": "..." }` and returns the final JSON itinerary payload.

# Secure Cloud Run Deploy (from backend/ folder)
gcloud secrets create tourist-openrouter-api-key --data-file=-
# Paste your API key, then press Ctrl+Z and Enter on Windows or Ctrl+D on macOS/Linux.

gcloud run deploy tourist-agent \
  --source . \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --port 8080 \
  --set-env-vars OPENROUTER_MODEL=stepfun/step-3.5-flash:free \
  --update-secrets OPENROUTER_API_KEY=tourist-openrouter-api-key:latest

# After deploy - update frontend API_BASE:
# In frontend/index.html, change:
#   const API_BASE = "http://localhost:8000";
# To:
#   const API_BASE = "https://tourist-agent-xxxx-el.a.run.app";

## GitHub Publish

Before pushing, make sure `git remote -v` points at your GitHub repository and GitHub CLI is installed and authenticated.