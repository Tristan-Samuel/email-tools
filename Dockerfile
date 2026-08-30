FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py gunicorn.conf.py ./

ENV ENV=production \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

EXPOSE 5001

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
