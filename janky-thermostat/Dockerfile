ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
RUN apk add --no-cache pigpio --repository=http://dl-cdn.alpinelinux.org/alpine/edge/testing/
RUN apk add --no-cache python3 py3-pip git build-base python3-dev

# copy your code in
WORKDIR /usr/src/jank
COPY . .

RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ensure run.sh is executable
RUN chmod a+x /usr/src/jank/run.sh

CMD [ "/usr/src/jank/run.sh" ]
