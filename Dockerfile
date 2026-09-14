FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . /app
RUN python -m pip install --no-cache-dir '.[bot]' \
    && useradd --create-home --uid 10001 lorcana \
    && chown -R lorcana:lorcana /app

USER lorcana

# Railway services override this command: worker uses lorcana-worker, bot uses lorcana-bot.
CMD ["lorcana-worker"]
