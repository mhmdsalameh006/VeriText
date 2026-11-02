# Deployment guidance

## VPS or Docker hosting

The Docker configuration serves the application over HTTP on container port 8000. Put a reverse proxy with TLS in front of it. Set a long, unique `APP_SECRET`, `TRUSTED_ORIGINS=https://integrity.example.edu`, and `COOKIE_SECURE=true`. Docker Compose stores application data in the named volume `veritext_data`. Back up and protect this volume.

### Container deployment

```bash
cp .env.example .env
# Set APP_SECRET, COOKIE_SECURE=true, and TRUSTED_ORIGINS=https://integrity.example.edu
# During first-time provisioning, create a persistent admin through the container CLI:
docker compose run --rm app python -m app.cli create-admin --email admin@example.edu
# Start the web service
docker compose up -d --build
```

In a reverse proxy, forward `Host`, `X-Forwarded-Proto` and client IP correctly, but configure proxy trust in the ASGI server before using forwarded headers for security decisions. Configure HTTPS, a firewall, maximum request body size and access logs. Do not expose SQLite or model artifacts through a web server static folder.

## Hostinger

- **Hostinger VPS**: Run Docker Compose on a Linux VPS with an HTTPS reverse proxy.
- **Shared/web hosting**: Check Python ASGI app and persistent worker support. Standard PHP-only shared hosting cannot directly run this long-lived FastAPI service.

## Production hardening backlog

The provided application is a working pilot, not a certified high-security platform. For institutional rollout: place it on a VPS with TLS, implement Redis-based rate limiting for login and uploads, add malware scanning, central log retention, key rotation, robust backups, OIDC/SSO, data retention policies and user data export/deletion mechanisms. Replace local SQLite/index with PostgreSQL + search infrastructure for multi-node operation, and use dedicated asynchronous workers for lengthy OCR/model tasks. Add institutional licensing for academic and web corpora.
