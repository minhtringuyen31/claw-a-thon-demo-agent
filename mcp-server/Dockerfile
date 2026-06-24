FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastmcp>=0.3.0" \
    "sqlalchemy>=2.0" \
    "pymysql>=1.1" \
    "pandas>=2.0" \
    "httpx>=0.27" \
    "python-dotenv>=1.0" \
    "pydantic>=2.0"

COPY . .

RUN mkdir -p /app/sessions

EXPOSE 8000

CMD ["python", "main.py"]
