FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Default: the live dashboard replaying the gray-failure scenario.
# Override CMD for the pipeline demo:  python3 demo.py --failure gray
CMD ["python3", "dashboard/app.py", "--host", "0.0.0.0", "--port", "5000", "--scenario", "gray"]
