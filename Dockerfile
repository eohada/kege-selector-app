FROM python:3.10-slim

WORKDIR /app

# Ставим системные пакеты для Postgres и компиляции
# 1. Принудительно заставляем apt использовать только IPv4 (решает 99% зависаний сети)
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

# 2. Жестко меняем зеркала на Яндекс ВО ВСЕХ файлах настроек apt
RUN find /etc/apt -type f -exec sed -i 's/deb.debian.org/mirror.yandex.ru/g' {} +
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    git \
    xvfb \
    python3-tk \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Установка основных веб-зависимостей без PyTorch/CUDA
RUN pip install --default-timeout=100 --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt

COPY . .

EXPOSE 8000
