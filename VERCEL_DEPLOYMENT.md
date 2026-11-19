# Vercel deployment notes

## What caused the build failure

The project hard-coded the MySQL backend in `EuphoriaDJ/settings.py`, but
`requirements.txt` did not install a MySQL driver. Vercel runs `collectstatic`
during the build, which initializes Django and imports the database backend.
Without `MySQLdb`, the build stopped before collecting any static files.

The local MySQL host (`localhost`) would also never be reachable from a Vercel
Function, so simply adding a driver would have moved the failure from build time
to runtime.

## What changed

- Database settings are now environment-driven:
  - `DATABASE_URL` supports hosted Postgres or MySQL.
  - `DB_ENGINE` / `DB_*` support explicit MySQL or SQLite configuration.
  - SQLite is used as a build-safe fallback when no database is configured.
- `PyMySQL` is included as a pure-Python MySQL fallback for Vercel, because
  `mysqlclient` requires Linux MySQL development headers that are not present in
  Vercel's Python image.
- `psycopg[binary]` is included for Vercel Postgres/Neon.
- Django is pinned below 6.0 so deployments use the same major version that was
  tested locally.
- `build.py` collects static files and applies migrations when a hosted database
  is configured.
- `vercel.json` points Vercel at `build.py`.
- Vercel hostnames are added to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
  automatically. Production mode is enabled by default on Vercel.
- Ollama is disabled by default on Vercel because a deployed site cannot reach
  your computer's local Ollama daemon.

## Configure the Vercel project

Add a Postgres database from **Storage → Create Database → Neon**. The
integration supplies the connection variables automatically.

Set these environment variables in **Vercel → Project → Settings → Environment
Variables**:

| Variable | Value |
| --- | --- |
| `SECRET_KEY` | A new random Django secret |
| `DEBUG` | `False` |
| `DATABASE_URL` | Supplied by the Neon integration |
| `DATABASE_URL_UNPOOLED` | Supplied by the Neon integration; used for migrations |
| `OLLAMA_ENABLED` | `false` |
| `SERVE_MEDIA` | `true` only for the demo catalog; use object storage otherwise |
| `ALLOWED_HOSTS` | Add a custom domain; your `*.vercel.app` host is automatic |
| `CSRF_TRUSTED_ORIGINS` | `https://your-domain.com` for custom domains |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | If email is required |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | If checkout is required |

Generate a production secret with:

```powershell
.\venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`build.py` runs migrations automatically whenever a hosted Postgres or MySQL
URL is configured. It prefers `DATABASE_URL_UNPOOLED` for schema changes and
uses the pooled `DATABASE_URL` at runtime. Watch the deployment log for the
migration step.

## Database contents

The first deployment starts with an empty database. Existing local MySQL data is
not copied automatically. This demo deployment keeps `SEED_DEMO_DATA=true` so
each build recreates the demo catalog images in `media/`; the command is
idempotent and leaves existing rows alone. Remove it once real product data and
object storage are configured.

This demo also sets `SERVE_MEDIA=true` so Django serves the generated images.
For real uploads, connect object storage; the serverless filesystem is
temporary.

## Remaining Vercel limitations

- **Ollama cannot run on Vercel.** With `OLLAMA_ENABLED=false`, the assistant
  uses its deterministic catalog search, recommendations, support, and order
  fallback. No cloud AI key is used.
- **Media files are ephemeral.** The demo images generated during the build are
  served by Django while `SERVE_MEDIA=true`. Real uploads need object storage
  such as S3 or Cloudinary because Vercel's filesystem is temporary.
- **SQLite is not persistent on Vercel.** The SQLite fallback only keeps builds
  working; use a hosted database for the deployed app.
- **Rotate exposed credentials.** The previous committed settings contained a
  database password and Django secret. Treat both as compromised, rotate them,
  and use Vercel environment variables from now on.

## Deployed project

- Public storefront: https://django-e-commerce-bharti20.vercel.app
- Vercel project: `bharti20/django-e-commerce`

## Local development

Local development continues to use the MySQL values in the gitignored `.env`
file. If you create a fresh checkout, copy `.env.example` to `.env` and fill in
either `DATABASE_URL` or the `DB_*` values.

Verify locally with:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe build.py
```
