# `biulder` is not an earlier stage, so Docker would try to pull an image
# called biulder. Expect an UNRESOLVED_DEPENDENCY warning suggesting `builder`,
# and UNREACHABLE_NODE for `builder`, which nothing uses as a result.
FROM golang:1.22 AS builder
WORKDIR /src
COPY . .
RUN go build -o /bin/server .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=biulder /bin/server /server
USER nonroot
ENTRYPOINT ["/server"]
