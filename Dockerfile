FROM python:3.10-slim

WORKDIR /app

# Ставим системные пакеты для Postgres и компиляции
# Принудительно используем IPv4 и исключаем лишние recomended пакеты (--no-install-recommends)
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Установка основных веб-зависимостей без PyTorch/CUDA
RUN pip install --default-timeout=100 --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
