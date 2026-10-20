# Builds, but with common mistakes. Expect DF_* rule findings:
# unpinned base, root user, apt-get update alone, missing -y (an error: the
# build stops at the prompt), consecutive RUNs, ADD for a local file.
FROM ubuntu:latest
WORKDIR /app
RUN apt-get update
RUN apt-get install curl
ADD app.sh /app/
CMD ["/app/app.sh"]
