FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY sql ./sql
RUN pip install --no-cache-dir .
CMD ["python","scripts/dashboard.py"]
