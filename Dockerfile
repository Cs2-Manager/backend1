FROM python:3.11
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev && pip install --no-cache-dir psycopg2-binary psycopg flask flask-cors flask-sqlalchemy python-dotenv bcrypt PyJWT
COPY app/ ./app/
COPY run.py .
EXPOSE 5000
CMD ["python", "run.py"]