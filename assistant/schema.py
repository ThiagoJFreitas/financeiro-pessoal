"""Schema description fed to the LLM. Only the analytics views are exposed — the
model never sees base tables, and every view is already scoped to the current
user, so generated SQL stays simple and safe.
"""

SCHEMA_PROMPT = """\
Você gera SQL para PostgreSQL. Use SOMENTE estas views (já filtradas para o
usuário atual). NÃO use as tabelas base. Valores monetários em reais (numeric).

view analytics.v_installments  -- uma linha por PARCELA (use para somas e "a pagar")
  competence_month date   -- mês de competência (sempre dia 1)
  due_date date           -- vencimento (pode ser nulo)
  amount numeric          -- valor da parcela
  paid boolean            -- paga?
  paid_date date
  number int, of_total int -- ex.: 2 de 6
  description text        -- descrição do lançamento
  kind text               -- 'EXPENSE' (despesa) ou 'INCOME' (receita)
  repeat_type text        -- 'SINGLE' | 'INSTALLMENT' | 'RECURRING'
  card_name text          -- nome do cartão (nulo se for boleto/conta)
  category_name text      -- categoria (pode ser nula)

view analytics.v_transactions -- uma linha por LANÇAMENTO (a compra/receita)
  description text, kind text, total_amount numeric, repeat_type text,
  repeat_count int, first_competence date, card_name text, category_name text,
  needs_review boolean

view analytics.v_cards        -- id, name, due_day, closing_day, "limit"
view analytics.v_categories   -- id, name, kind

Regras:
- Gere UM ÚNICO comando SELECT, sem ponto e vírgula, sem comentários.
- Para "quanto gastei/recebi", some v_installments.amount filtrando kind.
- Despesas usam kind='EXPENSE'; receitas kind='INCOME'.
- "a pagar" = paid = false. Use date_part/EXTRACT para filtrar ano/mês.
- "sobra"/"saldo" de um mês = receitas - despesas naquele mês de competência.
  Agrupe por mês com date_trunc('month', competence_month) e use
  SUM(CASE WHEN kind='INCOME' THEN amount ELSE -amount END) como saldo do mês.
- Para médias por mês, calcule o saldo por mês numa subconsulta e tire AVG().
- Use apenas as views analytics.v_*. Funções como date_trunc, EXTRACT,
  CURRENT_DATE e AVG são permitidas.
- Responda APENAS com o SQL, sem explicação e sem ```.
"""

EXAMPLES = [
    ("Quanto gastei com farmácia/saúde em 2026?",
     "SELECT COALESCE(SUM(amount),0) AS total FROM analytics.v_installments "
     "WHERE kind='EXPENSE' AND category_name='Saúde' AND date_part('year', competence_month)=2026"),
    ("Quanto ainda tenho a pagar no cartão NUBANK?",
     "SELECT COALESCE(SUM(amount),0) AS a_pagar FROM analytics.v_installments "
     "WHERE kind='EXPENSE' AND paid=false AND card_name='NUBANK'"),
    ("Total de despesas por categoria",
     "SELECT category_name, SUM(amount) AS total FROM analytics.v_installments "
     "WHERE kind='EXPENSE' GROUP BY category_name ORDER BY total DESC"),
    ("Quanto sobra de dinheiro por mês em média?",
     "SELECT AVG(saldo) AS media_sobra_mensal FROM ("
     "SELECT date_trunc('month', competence_month) AS mes, "
     "SUM(CASE WHEN kind='INCOME' THEN amount ELSE -amount END) AS saldo "
     "FROM analytics.v_installments GROUP BY 1) t"),
]
