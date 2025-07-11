ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.11
FROM ${BUILD_FROM}

# allow apt to run non-interactively
ENV DEBIAN_FRONTEND=noninteractive

# install pigpio C library, daemon & Python bindings
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      pigpio \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# copy your code in
WORKDIR /usr/src/my-addon
COPY run.sh .
COPY main.py .

# ensure run.sh is executable
RUN chmod a+x /usr/src/my-addon/run.sh

CMD [ "/usr/src/my-addon/run.sh" ]
