FROM python:3.12-slim

WORKDIR /app

# نصب Xray-core
RUN apt-get update && apt-get install -y curl unzip && \
    curl -L https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o /tmp/xray.zip && \
    unzip /tmp/xray.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/xray && \
    mkdir -p /usr/local/share/xray && \
    curl -L https://github.com/XTLS/Xray-core/releases/latest/download/geoip.dat -o /usr/local/share/xray/geoip.dat && \
    curl -L https://github.com/XTLS/Xray-core/releases/latest/download/geosite.dat -o /usr/local/share/xray/geosite.dat && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# پورت پیش‌فرض Node
EXPOSE 62050

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "62050"]
