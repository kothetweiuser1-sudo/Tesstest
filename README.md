# Tesstest
# Personal Bot Control API starter

Separate Railway web service starter.

Endpoints:
- GET / — API information
- GET /health — API health
- GET /admin/status — protected API status

Railway Variables:
- ADMIN_API_KEY: set a long random secret. Never commit it or put it in the APK.

This starter reports only the API process status. It is not connected to the Telegram bot yet and does not control scanning or retrieve scanner results.
