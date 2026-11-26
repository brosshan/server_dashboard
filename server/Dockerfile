FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY server/static ./static
COPY UPS狀態/web_client.py ./UPS狀態/web_client.py
COPY UPS狀態/snmp_client.py ./UPS狀態/snmp_client.py

# 建立非 root 使用者執行服務，落實最小權限原則 (CWE-250)
RUN useradd -m -u 1000 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
