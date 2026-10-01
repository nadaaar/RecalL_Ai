# RecallAI MVP

A small deployable MVP for the Dafinitiq AI application challenge.

## Features
- Upload PDF, TXT, or Markdown project material.
- Extract decisions, reasons, alternatives, and evidence.
- Ask natural-language questions about project decisions.
- Uses an open-source local LLM through Ollama when available; otherwise a deterministic extraction fallback keeps the demo functional.
- FastAPI backend + lightweight responsive frontend.

## Run locally
1. Install Python 3.11+.
2. `pip install -r requirements.txt`
3. Optional AI mode: install Ollama and run `ollama pull qwen2.5:3b`.
4. `uvicorn app:app --reload`
5. Open `http://127.0.0.1:8000`

## Demo document
Create `demo.txt` with:

We decided to use PostgreSQL because the product requires relational reporting and transactional consistency. MongoDB was considered as an alternative but was rejected because several reporting queries would be harder to maintain.

We chose Stripe because the MVP needs international card payments and an existing integration is available.

Upload it and ask: `Why did we choose PostgreSQL?`

## Deployment
This app is ready for Render, Railway, Fly.io, or another Python host. For a hosted LLM, set `OLLAMA_URL` to an accessible Ollama-compatible endpoint and `OLLAMA_MODEL` to the model name. For the challenge MVP, the fallback mode can be used for a deterministic public demo.
