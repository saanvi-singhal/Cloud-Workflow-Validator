FROM golang:1.21 AS builder
WORKDIR /src
COPY . .
RUN go build -o /app/server .

FROM alpine:latest AS runner
WORKDIR /app
COPY --from=builder /app/server /app/server
ENTRYPOINT ["/app/server"]
