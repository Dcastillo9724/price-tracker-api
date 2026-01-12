FROM python:3.12-slim

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      # base build deps (psycopg2/lxml/etc)
      gcc \
      python3-dev \
      libpq-dev \
      libxml2-dev \
      libxslt1-dev \
      zlib1g-dev \
      postgresql-client \
      # utils
      ca-certificates \
      curl \
      gnupg \
      unzip \
      wget \
      # libs que Chrome suele necesitar en slim
      libnss3 \
      libfontconfig1 \
      libxss1 \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdbus-1-3 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnspr4 \
      libx11-xcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxrandr2 \
      xdg-utils \
      fonts-liberation; \
    rm -rf /var/lib/apt/lists/*

# --- Agregar repo oficial de Google Chrome (sin apt-key) ---
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    mkdir -p /etc/apt/keyrings; \
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg; \
    chmod 644 /etc/apt/keyrings/google-chrome.gpg; \
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends google-chrome-stable; \
    rm -rf /var/lib/apt/lists/*

# --- Instalar Chromedriver compatible con la versión mayor de Chrome ---
RUN set -eux; \
    CHROME_MAJOR="$(google-chrome --version | awk '{print $3}' | cut -d. -f1)"; \
    echo "Chrome major: ${CHROME_MAJOR}"; \
    DRIVER_VERSION="$(curl -fsSL "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_MAJOR}")"; \
    echo "Chromedriver version: ${DRIVER_VERSION}"; \
    curl -fsSL -o /tmp/chromedriver.zip \
      "https://storage.googleapis.com/chrome-for-testing-public/${DRIVER_VERSION}/linux64/chromedriver-linux64.zip"; \
    unzip /tmp/chromedriver.zip -d /tmp/; \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver; \
    chmod +x /usr/local/bin/chromedriver; \
    rm -rf /tmp/chromedriver* /tmp/chromedriver.zip

# Verificar
RUN google-chrome --version && chromedriver --version

COPY requirements/ /app/requirements/

RUN pip install --upgrade pip \
    && pip install -r requirements/dev.txt

COPY . /app/

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]