#!/bin/bash
set -e

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-saremi}"

echo "==> Esperando a PostgreSQL en ${DB_HOST}:${DB_PORT}..."
until PGPASSWORD="$DB_PASSWORD" pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
  sleep 2
done
echo "==> PostgreSQL listo."

# Crear la base de datos si no existe
DB_EXISTS=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null || echo "")

if [ "$DB_EXISTS" != "1" ]; then
  echo "==> Creando base de datos '${DB_NAME}'..."
  PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    -c "CREATE DATABASE \"${DB_NAME}\";"
  echo "==> Base de datos creada."
fi

# Aplicar schema (idempotente — usa IF NOT EXISTS)
echo "==> Aplicando schema en '${DB_NAME}'..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -f /app/schema.sql -q
echo "==> Schema listo."

echo "==> Iniciando SarEmi API en 0.0.0.0:${API_PORT:-8000}..."
# RELOAD=true (dev) -> hot reload al editar el código montado como volumen.
# Sin RELOAD (prod) -> arranque normal con el código horneado en la imagen.
if [ "${RELOAD:-false}" = "true" ]; then
  echo "==> Modo desarrollo: hot reload ACTIVADO"
  exec uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}" --reload
else
  exec uvicorn main:app --host 0.0.0.0 --port "${API_PORT:-8000}"
fi
