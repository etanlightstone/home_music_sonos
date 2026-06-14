## NOTE THIS IS OUT OF DATE FOR MY CURRENT LAN, I'm just running it on the bare metal because running uvicorn twice
## for https and http on different ports
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "bash app.sh"]
