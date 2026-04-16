FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create persistent directories — data/ and logs/ are typically mounted as volumes
RUN mkdir -p data logs

CMD ["python", "main.py"]
