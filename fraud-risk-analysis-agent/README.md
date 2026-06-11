# fraud-risk-analysis-agent

A GreenNode AgentBase agent for fraud risk analysis, built with LangGraph.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- A GreenNode IAM Service Account ([create one here](https://iam.console.vngcloud.vn/service-accounts))

## Setup

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Configure credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

## Configure LLM

Set the following in `.env`:

```
LLM_API_KEY=your-api-key
LLM_BASE_URL=your-provider-base-url
LLM_MODEL=your-model-name
```

**Provider examples:**
- **GreenNode AIP**: Use `/agentbase-llm` to get an API key. Set `LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`
- **OpenAI**: Set `LLM_BASE_URL=https://api.openai.com/v1`, model e.g. `gpt-4o`

## Run Locally

```bash
uv run python main.py
```

The agent starts on `http://127.0.0.1:8080`.

```bash
curl -X POST http://127.0.0.1:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyze this transaction for fraud risk"}'
```

Health check:
```bash
curl http://127.0.0.1:8080/health
```

## Docker

Generate lock file first (required for `--frozen` build):
```bash
uv lock
```

Build and run:
```bash
docker build -t fraud-risk-analysis-agent .
docker run -p 8080:8080 --env-file .env fraud-risk-analysis-agent
```

## Deploy

Use `/agentbase-deploy` to build, push, and deploy to AgentBase Runtime.

## Project Structure

- `main.py` - Agent entrypoint (LangGraph graph + handler)
- `pyproject.toml` - Project dependencies (uv)
- `Dockerfile` - Container image definition
- `.greennode.json` - AgentBase configuration
- `.env.example` - Environment variable template