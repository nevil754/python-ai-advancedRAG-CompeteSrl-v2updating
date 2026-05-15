#!/bin/bash
# docker/sqlserver/entrypoint.sh
# Attende che SQL Server sia pronto, poi esegue init.sql
# Montato nel container sqlserver come comando di avvio

set -e

echo "Attendo SQL Server..."
until /opt/mssql-tools/bin/sqlcmd \
    -S localhost \
    -U SA \
    -P "$SA_PASSWORD" \
    -Q "SELECT 1" > /dev/null 2>&1; do
    sleep 2
done

echo "SQL Server pronto. Eseguo init.sql..."
/opt/mssql-tools/bin/sqlcmd \
    -S localhost \
    -U SA \
    -P "$SA_PASSWORD" \
    -i /docker-entrypoint-initdb.d/init.sql \
    -b   # esce con errore se il batch fallisce

echo "init.sql completato."
