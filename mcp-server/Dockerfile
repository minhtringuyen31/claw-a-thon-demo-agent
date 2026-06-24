FROM python:3.13-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY . .

RUN mkdir -p /app/sessions

EXPOSE 8000

CMD ["uv", "run", "python", "main.py"]
