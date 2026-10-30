FROM python:3.11
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini run.py ./
EXPOSE 5000
CMD ["sh", "-c", "python -m app.db_bootstrap && python run.py"]
