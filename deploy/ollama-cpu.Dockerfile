FROM alpine:3.23
RUN apk add --no-cache ollama
CMD ["ollama", "serve"]
