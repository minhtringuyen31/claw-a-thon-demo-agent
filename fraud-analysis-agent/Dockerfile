FROM python:3.13-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app ./app

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8080"]