# Dockerfile
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei

WORKDIR /app

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates \
      file \
      libc-bin \
      tzdata \
      sqlite3 \
      build-essential \
      curl \
    && update-ca-certificates \
    && ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 把程式放進容器
COPY app ./app
COPY start.sh /start.sh
RUN sed -i 's/\r$//' /start.sh && chmod +x /start.sh

EXPOSE 5000

ENV FLASK_APP=app.py \
    FLASK_ENV=development \
    FLASK_DEBUG=1


#CMD ["bash", "-lc", "sleep infinity"]
# 用 gunicorn 跑 Flask
# app.main:app = app/main.py 裡的 Flask app 物件名稱叫 app
CMD ["gunicorn","-w","2","-k","gthread","--threads","8","-b","0.0.0.0:5000","app.main:app"]
#CMD ["/start.sh"]

