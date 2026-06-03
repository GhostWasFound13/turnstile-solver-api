FROM python:3.11-slim-bookworm

# Install Firefox and dependencies
RUN apt-get update && apt-get install -y \
    wget \
    firefox-esr \
    firefox-esr-driver \
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
    libdbus-glib-1-2 \
    libxt6 \
    && rm -rf /var/lib/apt/lists/*

# Download GeckoDriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz && \
    tar -xzf geckodriver-v0.34.0-linux64.tar.gz && \
    chmod +x geckodriver && \
    mv geckodriver /usr/local/bin/ && \
    rm geckodriver-v0.34.0-linux64.tar.gz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_solver.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "8000", "--thread", "1", "--no-headless"]
