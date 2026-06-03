FROM python:3.11-slim-bookworm

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install matching ChromeDriver version 148 (matches installed Chrome)
RUN wget https://storage.googleapis.com/chrome-for-testing-public/148.0.7778.215/linux64/chromedriver-linux64.zip && \
    unzip chromedriver-linux64.zip && \
    chmod +x chromedriver-linux64/chromedriver && \
    mv chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    rm -rf chromedriver-linux64.zip chromedriver-linux64

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_solver.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 5072

CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "5072", "--thread", "1", "--no-headless"]
