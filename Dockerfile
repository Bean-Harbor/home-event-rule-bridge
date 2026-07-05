FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[discord,setup]"

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["home-rule-bridge"]
CMD ["run-discord"]
