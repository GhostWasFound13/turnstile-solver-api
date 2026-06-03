FROM python:3.11-slim-bookworm

# Install Firefox, Xvfb (virtual display), and dependencies
RUN apt-get update && apt-get install -y \
    wget \
    firefox-esr \
    xvfb \
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    && rm -rf /var/lib/apt/lists/*

# Install geckodriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz && \
    tar -xzf geckodriver-v0.34.0-linux64.tar.gz && \
    chmod +x geckodriver && \
    mv geckodriver /usr/local/bin/ && \
    rm geckodriver-v0.34.0-linux64.tar.gz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_solver.py .

# Start Xvfb and then the app (all in one line)
CMD Xvfb :99 -screen 0 1280x1024x24 & export DISPLAY=:99 && python api_solver.py --host 0.0.0.0 --port 8000 --thread 1 --no-headless
