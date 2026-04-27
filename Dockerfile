FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# --with-deps instala automaticamente as dependências do sistema para o Chromium,
# sincronizado com a versão do Playwright instalada via pip.
RUN playwright install --with-deps chromium

COPY . .

# Create persistent directories — data/ and logs/ are typically mounted as volumes
RUN mkdir -p data logs

CMD ["python", "main.py"]
