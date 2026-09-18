# Pipeline Control

A Python-based ATS mapping governance demo and backend service for controlled field mapping, validation, review, and exception handling.

This project is designed to show how AI-assisted mapping can accelerate onboarding while keeping the production runtime deterministic, reviewable, and governed by explicit approval and validation rules.

## What this project does

- Generates mapping proposals from source and target field names
- Validates mappings against rules and replay payloads
- Requires human approval before a mapping is treated as production-safe
- Tracks exceptions with ownership and resolution status
- Provides a web demo UI for monitoring and reviewing mappings
- Supports an optional AWS Bedrock proposer without making model execution part of the deterministic runtime

## Tech stack

- Python
- FastAPI
- React + TypeScript + Vite
- JSON-backed state stores for mapping and validation data
- Optional AWS Bedrock integration for AI-assisted drafting

## Repository structure

```text
.
├── api.py                  # FastAPI endpoints
├── pipeline.py             # Core processing, validation, and mapping logic
├── bedrock_proposer.py     # Optional Bedrock-backed mapping proposer
├── demo.py                 # Example pipeline runner
├── seed.py                 # Demo seed data generator
├── test_pipeline.py        # Automated tests
├── README.md               # Project documentation
├── .env.example            # Example environment file
├── .gitignore              # Repository security and cleanliness rules
├── frontend/               # Vite React frontend
├── fixtures/               # Sample payloads and schemas
├── demo-data/              # Local demo data (generated locally)
├── scripts/                # Utility scripts
└── requirements.txt        # Python dependencies
```

## Local setup

1. Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Then fill in any required local values. Do not commit real credentials.

## Run the backend

```powershell
python api.py
```

Or use Uvicorn:

```powershell
python -m uvicorn api:app --reload
```

## Run the frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

## Run the demo flow

```powershell
python demo.py
```

This project is built for controlled demo use and deterministic behavior. The runtime should never depend on a live model call to execute approved mappings.

## AWS Bedrock guidance

The project includes an optional Bedrock proposer for draft generation. The feature is intentionally separated from the deterministic runtime path and should only be used for proposal generation or repair flows.

If you use Bedrock locally:

1. Enable the model in the correct AWS region.
2. Set environment variables in your local shell or `.env` file.
3. Keep all credentials local and never commit secrets.

Example values are provided in `.env.example`.

## Security notes

- Do not commit secrets or API keys.
- Keep `.env` local only.
- Use `.env.example` as a safe template for required values.
- Any generated local state files should remain ignored by Git.

## License

This project is intended for internal demo and engineering use within the repository scope.
