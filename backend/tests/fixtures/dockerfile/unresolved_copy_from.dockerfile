FROM golang:1.22 AS builder
RUN go build -o /bin/tool .

FROM alpine:3.20
COPY --from=biulder /bin/tool /bin/tool
