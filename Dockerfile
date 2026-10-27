FROM python:3.12-slim

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt
COPY src ./src
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
ENV PYTHONPATH=/app/src ENVIRONMENT=production HOST=0.0.0.0 PORT=8000
EXPOSE 8000
USER appuser
CMD ["python", "-m", "main"]
