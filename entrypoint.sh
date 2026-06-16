#!/usr/bin/env bash
set -e

echo "Aguardando o Postgres..."
python - <<'PY'
import os, time, psycopg2
url = os.environ["DATABASE_URL"]
for i in range(60):
    try:
        psycopg2.connect(url).close()
        print("Postgres pronto.")
        break
    except Exception as e:
        time.sleep(1)
else:
    raise SystemExit("Postgres não respondeu a tempo.")
PY

echo "Aplicando migrations..."
python manage.py migrate --noinput

echo "Configurando schema analítico do assistente (views + role read-only)..."
python manage.py setup_assistant_db || echo "setup_assistant_db pulado (não-Postgres ou já configurado)."

# Carrega os dados iniciais apenas se o banco estiver vazio (primeiro boot).
if python manage.py shell -c "import sys; from django.contrib.auth.models import User; sys.exit(0 if User.objects.exists() else 1)"; then
    echo "Dados já existem — pulando loaddata."
else
    echo "Banco vazio — carregando initial_data.json (se existir)..."
    python manage.py loaddata initial_data || echo "Sem fixture — banco vazio (use import_xlsx para popular)."
fi

echo "Iniciando servidor..."
exec python manage.py runserver 0.0.0.0:8000
