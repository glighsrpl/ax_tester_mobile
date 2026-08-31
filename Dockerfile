FROM python:3.12
LABEL authors="p.bianco"

WORKDIR /app
COPY . /app

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.4/install.sh | bash \
 && . "/root/.nvm/nvm.sh" \
 && nvm install 22.3.0 \
 && nvm alias default 22.3.0 \
 && node -v && npm -v \
 && npm i
RUN python -m pip install -e . && rm -rf src/ax_tester.egg-info/
RUN playwright install --with-deps chrome

ENV GOOGLE_GENAI_USE_VERTEXAI="True"
ENV GOOGLE_CLOUD_PROJECT="concept-quality-it-1"
ENV GOOGLE_CLOUD_LOCATION="global"

EXPOSE 8080

CMD ["python", "mcp_server.py", "--host", "0.0.0.0", "--port", "8080"]
