# Branding (white-label)

This folder holds the logos of the results dashboard (`dashboard`, the Superset charts behind step 4's Results).
The top-bar logo, app name and theme colours are runtime settings: changing them needs no image rebuild. AISC is
the default (`branding/aisc/laif_logo.png`). The settings are read by `aisc_ext/branding.py`; the dashboard's
[README](../README.md) lists them with their defaults.

## Add a company

1. Create a folder and put the logo in it:

   ```
   branding/acme/logo.png
   ```

   The whole `branding/` folder is mounted at `/static/assets/branding/`, so that file is served at
   `/static/assets/branding/acme/logo.png`.

2. Set the variables (the logo as the browser requests it):

   ```env
   BRANDING_APP_NAME=Acme Assurance
   BRANDING_LOGO=/static/assets/branding/acme/logo.png
   BRANDING_PRIMARY=#0a7d32
   BRANDING_SECONDARY=#ff6600
   ```

   Standalone, they go in `.env`. In the AISC stack, `docker-compose.development.yml` passes `BRANDING_*` from
   the environment Docker Compose runs with.

   `BRANDING_PRIMARY` is enough: the darker and lighter shades are derived from it.

3. Apply: `docker compose up -d` (standalone), or restart the `dashboard` container in the AISC stack.

A `BRANDING_*` variable left unset or blank falls back to the AISC default. The top-bar background stays
Superset's white: Superset 4.1 has no setting for it.
