FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/data/hf-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-ara \
        tesseract-ocr-eng \
        libmagic1 \
        build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# World-writable so the container can run as an arbitrary host uid (see the
# `user:` directive in docker-compose.yml) and still write download scratch here.
RUN mkdir -p temp && chmod 777 temp

CMD ["python", "bot.py"]
