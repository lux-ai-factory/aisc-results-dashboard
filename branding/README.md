# Branding (white-label)

The top-bar logo, app name and theme colours are runtime configuration: changing
them needs no image rebuild. AISC is the default (`branding/aisc/`).

## Add a company

1. Create a folder and drop the logo:

   ```
   branding/acme/logo.png
   ```

   The whole `branding/` directory is mounted at
   `/static/assets/branding/`, so that file is served at
   `/static/assets/branding/acme/logo.png`.

2. Point `.env` at it (the browser-facing path):

   ```env
   BRANDING_APP_NAME=Acme Assurance
   BRANDING_LOGO=/static/assets/branding/acme/logo.png
   BRANDING_PRIMARY=#0a7d32
   BRANDING_SECONDARY=#ff6600
   ```

   `BRANDING_PRIMARY` is enough: the darker and lighter shades are derived
   from it (`aisc_ext/branding.py`).

3. Apply: `docker compose up -d` (standalone), or restart the `dashboard`
   container in the AISC stack, which passes the `BRANDING_*` variables from the
   environment docker compose runs with.

Leave the `BRANDING_*` vars blank to fall back to the default AISC identity.
