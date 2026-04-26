FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema necessárias para o Chromium (Playwright)
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

# Create persistent directories — data/ and logs/ are typically mounted as volumes
RUN mkdir -p data logs

CMD ["python", "main.py"]
