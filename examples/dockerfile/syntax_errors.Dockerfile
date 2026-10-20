# Docker refuses to build this file.
# Expect DOCKERFILE_SYNTAX_ERROR for: HEALTHCHECK without CMD, ONBUILD ONBUILD,
# and the unknown instruction START. Also DF_EXEC_FORM_NOT_JSON for the
# single-quoted CMD, which builds but cannot start.
FROM nginx:1.27-alpine
HEALTHCHECK --interval=5m curl -f http://localhost/
ONBUILD ONBUILD RUN echo nested
CMD ['nginx', '-g', 'daemon off;']
START nginx
