FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY webcam.py /app/webcam.py
RUN chmod +x /app/webcam.py

VOLUME ["/data/images"]
ENTRYPOINT ["python","/app/webcam.py"]

