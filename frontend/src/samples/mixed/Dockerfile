FROM alpine:3.20

RUN apk update && \
    apk add --no-cache bash curl jq && \
    curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

COPY install-tools.sh scan.sh /usr/local/bin/
RUN sh /usr/local/bin/install-tools.sh

ENTRYPOINT ["/usr/local/bin/scan.sh"]
