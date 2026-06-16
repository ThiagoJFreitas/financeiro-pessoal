# Financeiro Pessoal

App web de planejamento financeiro (Django) que substitui a planilha de controle
de despesas, faturas de cartão e receitas. Cada usuário tem um planejamento
isolado e privado; o sistema é multiusuário e escalável.

## Funcionalidades

- **Lançamentos** de despesas e receitas com **parcelamento** (divide o total em N
  meses) e **recorrência** (repete o valor cheio por N meses).
- **Cartões** com vencimento/fechamento e tela de **fatura por mês**.
- **Resumo mensal** com receitas, despesas e **sobra**, mais gráficos
  (receita × despesa, despesas por categoria, sobra ao longo do tempo).
- **Relatório "A Pagar"** detalhado, com filtros (mês, cartão, categoria, status).
- **Categorias** personalizáveis.
- **Login/cadastro** por usuário — dados de um usuário nunca aparecem para outro.

## Rodar localmente (Windows)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # liga DEBUG=True para desenvolvimento local
python manage.py migrate
python manage.py import_xlsx --create-user   # opcional: importa a planilha e cria thiago/tj123
python manage.py runserver
```

Acesse http://127.0.0.1:8000 e entre com **thiago / tj123** (ou crie uma conta nova).

> Para um superusuário do admin (`/admin`): `python manage.py createsuperuser`.

## Estrutura

| Camada | Arquivo | Papel |
|--------|---------|-------|
| Modelos | `finance/models.py` | `Transaction` gera `Installment`; tudo tem `owner` |
| Regras  | `finance/services.py` | geração de parcelas, resumo mensal, fatura |
| Consultas | `finance/selectors.py` | queries filtradas por usuário (gráficos, "a pagar") |
| Views/URLs | `finance/views.py`, `finance/urls.py` | telas |
| Importador | `finance/management/commands/import_xlsx.py` | migra a planilha |

A "sobra", a fatura de cada cartão e os gráficos são **sempre calculados** a
partir das parcelas — nunca números digitados que possam ficar desatualizados.

## Deploy na nuvem (Render)

### Opção 1 — Blueprint (1 clique, recomendado)

Este repo já inclui um [`render.yaml`](render.yaml). No [Render](https://render.com):
**New > Blueprint**, aponte para o repositório no GitHub e confirme. Ele cria o
banco Postgres e o web service, gera `SECRET_KEY`, conecta o `DATABASE_URL` e roda
`migrate` sozinho. Depois, abra o **Shell** do serviço e crie seu acesso:
`python manage.py import_xlsx --create-user` ou `python manage.py createsuperuser`.

> O `render.yaml` usa `ALLOWED_HOSTS=.onrender.com`. Se você usar um domínio
> próprio, adicione-o lá e em `CSRF_TRUSTED_ORIGINS`.

### Opção 2 — Manual

1. Suba este repositório no GitHub.
2. No [Render](https://render.com): **New > Web Service**, aponte para o repo.
   - Build: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - Start: `gunicorn config.wsgi`
3. **New > PostgreSQL** e copie a *Internal Database URL*.
4. No Web Service, em **Environment**, configure:
   - `DATABASE_URL` = a URL do Postgres
   - `SECRET_KEY` = uma chave nova e secreta
   - `DEBUG` = `False`
   - `ALLOWED_HOSTS` = `seu-app.onrender.com`
   - `CSRF_TRUSTED_ORIGINS` = `https://seu-app.onrender.com`
5. O `release` do `Procfile` roda `migrate` automaticamente. Depois, crie seu
   usuário pelo painel **Shell** do Render: `python manage.py import_xlsx --create-user`
   ou `python manage.py createsuperuser`.

O mesmo código roda em Railway ou Fly.io — só garanta `DATABASE_URL` e as
variáveis acima. Localmente, sem `DATABASE_URL`, ele usa SQLite.

## Testes

```powershell
python manage.py test finance
```
