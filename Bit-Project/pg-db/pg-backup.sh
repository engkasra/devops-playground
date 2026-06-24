#!/bin/bash

# NOT TEST YET!

PG_HOST=""
PG_PORT="5432"
PG_USER=""
PG_DB=""
BACKUP_DIR="/path"
DATE=$(date +"%Y-%m-%d")
BACKUP_FILE="$BACKUP_DIR/backup-$DATE.sql"

export PGPASSWORD=""

mkdir -p $BACKUP_DIR

pg_dump -h $PG_HOST -p $PG_PORT -U $PG_USER $PG_DB > $BACKUP_FILE

if [ $? -eq 0 ]; then
  echo "[$(date)] Backup successful: $BACKUP_FILE"
else
  echo "[$(date)] Backup failed!"
  exit 1
fi

find $BACKUP_DIR -type f -mtime +7 -name '*.sql' -exec rm {} \;
