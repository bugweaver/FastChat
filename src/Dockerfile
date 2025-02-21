FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update \
  && apt-get -y install \
    --no-install-recommends \
    gcc g++ libpq-dev \
  && apt-get clean

RUN pip install --upgrade pip

COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --no-root

COPY . .
