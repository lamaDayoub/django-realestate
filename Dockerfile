# Dockerfile
# Use an official Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set a temporary working directory for Pipenv installation
WORKDIR /tmp_build

# Install system dependencies needed for psycopg2-binary, Pillow, and curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        zlib1g-dev \
        libjpeg-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Pipenv
ENV PIPENV_HOME="/usr/local/pipenv"
ENV PATH="$PIPENV_HOME/bin:$PATH"
RUN pip install pipenv

# Copy Pipfile and Pipfile.lock into the temporary build directory
COPY Pipfile Pipfile.lock ./

# Install project dependencies from Pipfile.lock
# --deploy: Fails if Pipfile.lock is not up-to-date or if hash mismatches.
# --system: Installs packages into the system Python environment inside the container.
RUN pipenv install --deploy --system --verbose

# Create the actual application directory
WORKDIR /app

# Copy the Django project subdirectory into /app/realestate inside the container
# The first "./realestate" refers to the host's "realestate" subdirectory
# The second "/app/realestate" refers to the destination inside the container
COPY ./realestate /app/realestate

# Set the working directory to the Django project root inside the container
WORKDIR /app/realestate

# Expose ports for both runserver and daphne
EXPOSE 8000
EXPOSE 8001

# Define environment variable for Django settings module
ENV DJANGO_SETTINGS_MODULE=realestate.settings

# Default command (overridden by docker-compose for specific services)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]