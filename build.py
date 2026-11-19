"""Vercel build entrypoint for the Django storefront.

Vercel runs this after installing requirements. Static files are collected for
the Vercel CDN. Database migrations run only when a real hosted database is
configured, so a build without database env vars still succeeds.

Local development does not use this script; run manage.py directly.
"""

import os
import subprocess
import sys


def run(*args):
    print(f'+ python manage.py {" ".join(args)}', flush=True)
    subprocess.check_call([sys.executable, 'manage.py', *args])


def configured_database():
    database_url = os.getenv('DATABASE_URL', '').strip().lower()
    if database_url.startswith(('postgres://', 'postgresql://', 'mysql://')):
        return True
    engine = os.getenv('DB_ENGINE', '').strip()
    return engine in {
        'django.db.backends.postgresql',
        'django.db.backends.mysql',
    }


def main():
    run('collectstatic', '--noinput')
    if configured_database():
        run('migrate', '--noinput')
        if os.getenv('SEED_DEMO_DATA', '').strip().lower() in {
            '1', 'true', 'yes', 'on',
        }:
            run('populate_demo_data')
    else:
        print(
            'No hosted database configured; skipped migrations. '
            'Set DATABASE_URL in Vercel before using the deployed site.',
            flush=True,
        )


if __name__ == '__main__':
    main()
