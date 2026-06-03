FROM python:3.11-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and all system dependencies
RUN python -m patchright install chromium
RUN python -m patchright install-deps chromium

COPY . .

CMD ["python", "api_solver.py", "--host", "0.0.0.0", "--port", "8000"]
