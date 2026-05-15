# Stage 1: Build the Vite/React app
# Use the slim node image instead of the devcontainer image; the devcontainer
# variant is ~1.5GB while slim is ~250MB and is sufficient for `npm ci` +
# `npm run build`. The final NGINX runtime image is unaffected.
FROM node:22-bookworm-slim AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .

# Placeholder values inlined into the JS bundle by Vite at build time.
# At container start, env.sh replaces these literal strings with real
# values from the container environment.
ENV VITE_AAD_TENANT_ID=APP_TENANT_ID \
    VITE_AAD_CLIENT_ID=APP_WEB_CLIENT_ID \
    VITE_AAD_API_SCOPE=APP_API_SCOPE \
    VITE_REDIRECT_URI=APP_REDIRECT_URI \
    VITE_API_BASE_URL=APP_API_BASE_URL

RUN npm run build

# Stage 2: Serve with NGINX
FROM mcr.microsoft.com/azurelinux/base/nginx:1.25

COPY --from=builder /app/dist /usr/share/nginx/html
COPY /nginx-custom.conf /etc/nginx/nginx.conf

COPY env.sh /docker-entrypoint.d/env.sh
RUN chmod +x /docker-entrypoint.d/env.sh \
    && sed -i 's/\r$//' /docker-entrypoint.d/env.sh \
    && chown -R 101:0 /usr/share/nginx/html /etc/nginx /var/log/nginx /docker-entrypoint.d \
    && chmod -R g=u /usr/share/nginx/html /etc/nginx /var/log/nginx /docker-entrypoint.d

USER 101

EXPOSE 3000

CMD ["/bin/sh", "-c", "/docker-entrypoint.d/env.sh && nginx -g 'daemon off;'"]
