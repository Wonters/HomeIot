FROM tiangolo/uvicorn-gunicorn-fastapi:python3.10-slim-2023-07-31

COPY ./requirements.txt /app/requirements.txt

RUN apt-get update && apt-get install -y cron
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY ./app /app
COPY ./start.sh /start-with-cron.sh

RUN chmod +x /app/retrieve.sh /start-with-cron.sh && python /app/cron.py

CMD ["/start-with-cron.sh"]

