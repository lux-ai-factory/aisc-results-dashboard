# Branding (white-label)

The bar logo, app name and theme colors are **runtime config** — no image
rebuild to change them. AISC is the built-in default tenant (`branding/aisc/`).

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

   `BRANDING_PRIMARY` is enough — the dark/light shades are derived
   automatically (`aisc_ext/branding.py`).

3. Apply:

   ```
   docker compose up -d
   ```

Leave the `BRANDING_*` vars blank to fall back to the default AISC identity.
