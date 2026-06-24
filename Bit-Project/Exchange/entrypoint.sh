#!/bin/sh

python manage.py makemigrations
python manage.py migrate
python manage.py collectstatic --no-input --clear --verbosity=0

python manage.py runserver 0.0.0.0:8000

exec "$@"

