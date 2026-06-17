# 💰 Financeiro Pessoal

Aplicação web de **planejamento financeiro** feita em Django. Nasceu para substituir
uma planilha de controle de despesas, faturas de cartão e receitas — com banco de
dados de verdade, relatórios, gráficos e até um **assistente de IA local** que
responde perguntas sobre suas contas em português.

É **multiusuário e isolado**: cada conta tem seu próprio planejamento, e os dados de
um usuário nunca aparecem para outro.

> Projeto pessoal/educacional. Roda 100% local com Docker e também faz deploy fácil
> na nuvem (Render/Railway/Fly).

---

## ✨ Funcionalidades

- **Resumo mensal** no formato de extrato (como a planilha): uma linha por cartão
  (somatório da fatura) e uma por conta (aluguel, plano de saúde, etc.), com
  **vencimento**, **valor** e um botão **"Paguei"** que marca como pago e pinta a
  linha de verde. Totais de **a pagar**, **a receber** e **sobra**.
- **Lançamentos** de despesas/receitas com **parcelamento** (divide o total em N
  meses) e **recorrência** (repete o valor cheio por N meses). Geração automática
  das parcelas, com tratamento de arredondamento de centavos.
- **Seleção múltipla** na lista de lançamentos: marcar vários e **confirmar
  pagamento** ou **excluir** em massa (com confirmação).
- **Cartões** com vencimento/fechamento, **fatura por mês** e gráfico **burn-down**
  (a dívida do cartão diminuindo ao longo dos meses).
- **Detalhe do parcelamento**: progresso "X/N", **antecipar**/**quitar**/**excluir**.
- **Relatório "A Pagar"** com filtros (mês, cartão, categoria, status) e
  totalização **por cartão ou por categoria**, com "quando acaba".
- **Gráficos** (Chart.js): receita × despesa, despesas por categoria, sobra no tempo.
- **Assistente de IA (text-to-SQL)** rodando **localmente** (Ollama): pergunte
  *"quanto sobra por mês em média?"* e receba a resposta em português.
- **Categorias** personalizáveis.
- **Autenticação completa**: login, cadastro e **"esqueci a senha"** (reset por e-mail).
- **Importador** da planilha original (`extra_novembro.xlsx`).

---

## 🧱 Stack

- **Backend**: Django 4.2 (LTS), Python 3.12
- **Banco**: PostgreSQL (Docker) / SQLite (local sem Docker)
- **Front**: templates Django + Bootstrap 5 + Chart.js
- **IA**: Ollama (modelo `qwen2.5-coder:7b`) — local, sem nuvem
- **Infra**: Docker Compose (web + db + ollama), WhiteNoise (estáticos), Gunicorn
- **Segurança**: django-axes (rate-limit), django-otp (2FA no admin)

---

## 🚀 Como rodar

### Opção A — Docker (recomendado: já inclui Postgres e o assistente)

Pré-requisito: **Docker Desktop** rodando.

```bash
docker compose up --build
# numa segunda aba, baixe o modelo da IA (só na 1ª vez, ~4.7 GB):
docker compose exec ollama ollama pull qwen2.5-coder:7b
```

- App: <http://localhost:8000> — login **`thiago` / `tj123`** (dados de exemplo são
  carregados no 1º boot, **se** existir o fixture local).
- Postgres exposto em `localhost:5432` (`financeiro` / `financeiro`) para você
  plugar qualquer ferramenta de BI.
- Rodar os testes: `docker compose exec web python manage.py test`

> Máquina sem GPU ou pouca RAM? Troque `OLLAMA_MODEL` no `docker-compose.yml` por
> `qwen2.5-coder:1.5b` (mais rápido, SQL um pouco menos preciso).

### Opção B — Local sem Docker (SQLite)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # liga DEBUG=True p/ desenvolvimento
python manage.py migrate
python manage.py runserver
```

Crie sua conta em <http://127.0.0.1:8000/cadastro/>, ou importe a planilha (veja
abaixo). O **assistente de IA requer Postgres** — não funciona no modo SQLite.

> Sem o arquivo `.env`, o app roda em modo produção (`DEBUG=False`) e exige as
> variáveis de ambiente. Para desenvolver, sempre crie o `.env`.

---

## 📥 Importar a planilha (opcional)

```bash
python manage.py import_xlsx --create-user        # cria thiago/tj123 e importa
python manage.py seed_categories                  # cria categorias e classifica
```

A importação é **best-effort**: os itens entram marcados como **"pendente de
revisão"** para você conferir os valores (há diferenças por inconsistências da
própria planilha). O caminho padrão do arquivo pode ser ajustado com `--file`.

---

## 🤖 O Assistente de IA (text-to-SQL)

Em **`/assistente/`**, você pergunta em português e a IA gera o SQL, executa e
responde. **Tudo roda na sua máquina** (Ollama em container) — nenhum dado
financeiro sai do PC.

A segurança é em **camadas, garantidas pelo banco** (não por "confiar" na IA):

1. **Views por usuário**: a IA só enxerga views (`analytics.v_*`) que filtram as
   linhas pelo usuário logado (via variável de sessão do Postgres). Se a sessão não
   estiver setada, retornam **zero linhas** (falha fechada).
2. **Usuário somente-leitura**: o assistente conecta com um papel do Postgres que
   **não lê as tabelas base, não escreve, não cria nada** — só `SELECT` nas views.
3. **Validador de SQL**: bloqueia qualquer coisa que não seja um único `SELECT`
   (sem `DROP`/`ALTER`/`DELETE`, sem `;`, sem `set_config`, etc.) e força `LIMIT`.

A primeira pergunta após ~5 min de ociosidade é mais lenta (o modelo recarrega na
memória); as seguintes respondem em ~20–30 s (CPU).

---

## 🔐 Admin e segurança

O painel administrativo do Django fica em **`/chefao`** (não em `/admin`, que
retorna 404 — dificulta bots). Está protegido por:

- **2FA obrigatório** (django-otp): além de usuário e senha, exige um código de 6
  dígitos de um app autenticador (Google Authenticator/Authy). Para cadastrar/renovar
  o 2FA de um usuário e ver o QR Code:
  ```bash
  docker compose exec web python manage.py setup_2fa --user thiago
  ```
- **Rate-limit de login** (django-axes): trava após 5 tentativas erradas (por
  usuário), destrava sozinho em 30 min. Destravar manual: `python manage.py axes_reset`.
- **HTTPS/HSTS, cookies seguros e SSL redirect**: ligados automaticamente quando
  `DEBUG=False`.

Trocar senha dentro do `/chefao`: link "Alterar senha" no topo, ou em
**Users → usuário → senha**.

> ⚠️ A senha-semente `tj123` é fraca e serve só para começar. **Troque-a** antes de
> expor o app na internet.

### Sobre o `SECRET_KEY`

É a **chave criptográfica do Django** — usada para assinar cookies de sessão, tokens
de CSRF e de reset de senha. **Quem tem essa chave consegue falsificar sessões e se
passar por qualquer usuário.** Por isso:

- O valor no `settings.py`/`docker-compose.yml` é só de **desenvolvimento** (rotulado
  `django-insecure-` / `nao-use-em-producao`).
- Em **produção**, defina um valor forte e aleatório via variável de ambiente
  (o `render.yaml` gera um automaticamente). Gere um assim:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
- O `.env` (que guarda a chave real) **nunca é versionado** (está no `.gitignore`).

---

## ⚙️ Variáveis de ambiente

Todas têm padrão seguro; configure em `.env` (local) ou no painel do host (produção).
Veja o [`.env.example`](.env.example).

| Variável | Para que serve |
|----------|----------------|
| `SECRET_KEY` | Chave criptográfica (obrigatória e secreta em produção) |
| `DEBUG` | `True` em dev, `False` em produção |
| `ALLOWED_HOSTS` | Domínios permitidos (ex.: `meuapp.onrender.com`) |
| `CSRF_TRUSTED_ORIGINS` | Origem https confiável p/ POST em produção |
| `DATABASE_URL` | Conexão do Postgres (vazio = SQLite local) |
| `ASSISTANT_DATABASE_URL` | Conexão **somente-leitura** usada só pelo assistente |
| `OLLAMA_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT` | Configuração do assistente de IA |
| `EMAIL_HOST` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | SMTP do "esqueci a senha" (sem isso, o link vai para o log) |

---

## 🏗️ Como funciona (arquitetura)

O coração do modelo: um **`Transaction`** (a compra/receita) gera um ou mais
**`Installment`** (parcelas). **Tudo o que as telas mostram** — fatura do cartão,
sobra do mês, gráficos — é **sempre calculado** somando parcelas, nunca um número
digitado que possa ficar desatualizado.

Todo registro tem um campo **`owner`** e todas as consultas filtram por ele — é isso
que garante o isolamento entre contas.

| Camada | Arquivo | Papel |
|--------|---------|-------|
| Modelos | `finance/models.py` | `Transaction` → `Installment`; tudo com `owner` |
| Regras de negócio | `finance/services.py` | geração de parcelas, resumo mensal, fatura |
| Consultas | `finance/selectors.py` | queries por usuário (extrato, gráficos, "a pagar") |
| Views/URLs | `finance/views.py`, `finance/urls.py` | telas |
| Assistente | `assistant/` | text-to-SQL seguro (views, guard, runner) |
| Importador | `finance/management/commands/import_xlsx.py` | migra a planilha |

---

## ☁️ Deploy na nuvem (Render)

### Blueprint (1 clique)

O repo inclui um [`render.yaml`](render.yaml). No [Render](https://render.com):
**New → Blueprint**, aponte para este repositório e confirme. Ele cria o Postgres e
o web service, **gera o `SECRET_KEY`**, conecta o `DATABASE_URL` e roda `migrate`
sozinho. Depois, no **Shell** do serviço, crie seu acesso:

```bash
python manage.py createsuperuser
python manage.py setup_2fa --user <seu-usuario>   # opcional: 2FA no admin
```

> O assistente de IA (Ollama) é, por ora, um recurso **local** — exige um host com
> bastante RAM. O web + banco funcionam normalmente na nuvem sem ele.

O mesmo código roda em **Railway** ou **Fly.io** — basta fornecer `DATABASE_URL` e as
variáveis acima.

---

## 🧪 Testes

```bash
docker compose exec web python manage.py test      # no Docker (Postgres)
# ou, local:
python manage.py test
```

Cobrem: geração de parcelas e arredondamento, resumo mensal, **isolamento entre
usuários**, ações em massa, segurança do assistente (validador de SQL + isolamento
por sessão), reset de senha e endurecimento do admin.

---

## 🔒 Privacidade

- O **código** vai para o GitHub; os **dados** (banco) e **segredos** (`.env`) **não**.
- O assistente de IA roda **local** — nenhuma informação financeira é enviada a
  serviços externos.
- `db.sqlite3`, `.env`, `venv/` e o fixture com dados reais estão no `.gitignore`.
