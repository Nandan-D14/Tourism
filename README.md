# Tourist Place Finder Agent

A production-minded Google ADK + FastAPI project that recommends five tourist places, builds a realistic one-day itinerary, and now serves the frontend and backend together from one container for Cloud Run.

## Project Structure

- `backend/`: ADK app, FastAPI API, and environment templates.
- `frontend/`: single-file interface served by the FastAPI app.
- `Dockerfile`: root-level single-container image for the full project.

## Prerequisites

- Python 3.11 or newer
- A valid backend API key configured in `backend/.env`
- Google Cloud SDK if you want to deploy with `gcloud`: https://cloud.google.com/sdk/docs/install
- Docker Desktop if you want to build and test the container locally

## Security Notes

- Keep real credentials only in `backend/.env`, Secret Manager, or your shell environment.
- Do not commit `.env`, service account JSON files, or private keys.
- Root `.gcloudignore` and `.dockerignore` keep local secrets, caches, and logs out of both Cloud Run source uploads and Docker image layers.

# Local Dev Run
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Add your backend API key
uvicorn main:app --reload --port 8000
# Open http://localhost:8000

# Test with curl
curl -X POST http://localhost:8000/find-places \
  -H "Content-Type: application/json" \
  -d '{"city": "Shimoga", "interest": "waterfalls"}'

# Single Docker Run (frontend + backend together)
docker build -t tourist-agent .
docker run --rm -p 8080:8080 --env-file backend/.env tourist-agent
# Open http://localhost:8080

# ADK Dev UI (bonus - great for hackathon demo)
cd backend && adk web

## API Endpoints

- `GET /`: serves the frontend UI from the same FastAPI container.
- `GET /health`: basic health response for the FastAPI wrapper.
- `POST /find-places`: takes `{ "city": "...", "interest": "..." }` and returns the final JSON itinerary payload.

# Secure Cloud Run Deploy (from repo root)
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

# After deploy, open the Cloud Run service URL directly.
# The same container serves both the UI and the API.