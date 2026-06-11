FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "-w", "1", "--timeout", "300", "-b", "0.0.0.0:8080", "web_dashboard_cloud:app"]
