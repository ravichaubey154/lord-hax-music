FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    nodejs \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    "discord.py[voice]>=2.7.1" \
    "davey>=0.1.6,<0.2" \
    "yt-dlp[default]>=2025.1.0" \
    "pycryptodome>=3.17.0" \
    "python-dotenv>=1.0.0"

COPY bot.py config.py music.py ./

CMD ["python", "-u", "bot.py"]
