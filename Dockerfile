FROM python:3.12

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

RUN chown -R appuser:appuser /app

VOLUME ["/app/seen_jobs.db"]

USER appuser

CMD ["python", "main.py"]