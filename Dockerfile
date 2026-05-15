FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create uploads directory
RUN mkdir -p uploads

EXPOSE 8000

# Use uvicorn with single worker (Railway free tier = 512MB RAM)
CMD ["uvicorn", "app.api.v1.endpoints:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
