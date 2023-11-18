FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10-slim-2023-07-31

COPY ./requirements.txt /app/requirements.txt

RUN apt-get update && apt-get install -y cron
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY ./app /app

RUN python /app/cron.py
