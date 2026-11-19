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


def database_url_for_migrations():
    for name in (
        'DATABASE_URL_UNPOOLED',
        'POSTGRES_URL_NON_POOLING',
        'DATABASE_URL',
        'POSTGRES_URL',
    ):
        value = os.getenv(name, '').strip()
        if value.startswith(('postgres://', 'postgresql://', 'mysql://')):
            return value
    return ''


def configured_database():
    if database_url_for_migrations():
        return True
    engine = os.getenv('DB_ENGINE', '').strip()
    return engine in {
        'django.db.backends.postgresql',
        'django.db.backends.mysql',
    }


def main():
    run('collectstatic', '--noinput')
    if configured_database():
        # Use the direct Neon connection for schema changes; pooled PgBouncer
        # connections are intended for the runtime and can reject some DDL.
        migration_url = database_url_for_migrations()
        if migration_url:
            os.environ['DATABASE_URL'] = migration_url
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
