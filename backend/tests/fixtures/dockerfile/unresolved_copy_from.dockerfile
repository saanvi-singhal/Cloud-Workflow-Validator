FROM alpine:latest
COPY --from=unknown_stage /bin/tool /bin/tool
