FROM python:3.12-slim

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Directorio de trabajo
WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    python3-dev \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements/ /app/requirements/

# Instalar dependencias Python
RUN pip install --upgrade pip && \
    pip install -r requirements/dev.txt

# Copiar proyecto
COPY . /app/

# Puerto
EXPOSE 8000

# Comando por defecto
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]