"""Import the legacy 'extra_novembro.xlsx' planning into the database.

Best-effort, one-time migration. The card detail tabs are the source of truth
for installments (exact per-month amounts), and from the CONTAS tab we only
bring NON-card expenses plus the income block, so card invoices aren't counted
twice.

Usage:
    python manage.py import_xlsx --create-user
    python manage.py import_xlsx --file "C:/path/extra_novembro.xlsx" --user thiago
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from finance.models import Card, Installment, Kind, RepeatType, Transaction

DEFAULT_FILE = "extra_novembro.xlsx"  # ajuste com --file
# Generic seed credentials. The account is created with a temporary password and
# flagged to force a real password on first login.
DEFAULT_USERNAME = "user"
DEFAULT_PASSWORD = "pass"

# Months whose first occurrence sits in 2025 on this planning's timeline.
START_YEAR = 2025
NEXT_YEAR = 2026

MONTH_ABBR = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

# Sheet name -> Card name. These tabs are the source of truth for installments.
CARD_SHEETS = {
    "latam": "LATAM",
    "NUBANK": "NUBANK",
    "PASSAI": "PASSAI",
    "extra": "PICPAY",
}

# CONTAS expense labels that ARE card invoices -> which Card they map to.
# When the detail sheet already covers that (card, month) we skip the CONTAS
# total to avoid double counting; otherwise we import the total as a single
# expense on the card (early months have no detail sheet).
LABEL_TO_CARD = {
    "NUBANK": "NUBANK", "PASSAI": "PASSAI", "LATAM": "LATAM",
    "EXTRA": "PICPAY", "PICPAY": "PICPAY",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def month_number(name) -> int | None:
    if not name:
        return None
    key = strip_accents(str(name)).strip().lower()[:3]
    return MONTH_ABBR.get(key)


def resolve_year(month_num: int) -> int:
    """Nov/Dec belong to 2025; everything else to 2026 on this timeline."""
    return START_YEAR if month_num >= 11 else NEXT_YEAR


def comp(month_num: int) -> date:
    return date(resolve_year(month_num), month_num, 1)


def num(value):
    """Return a Decimal if the cell holds a number, else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    return None


INSTALLMENT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


class Command(BaseCommand):
    help = "Importa o extra_novembro.xlsx para o banco."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=DEFAULT_FILE)
        parser.add_argument("--user", default=DEFAULT_USERNAME)
        parser.add_argument("--create-user", action="store_true",
                            help=f"Cria o usuário {DEFAULT_USERNAME}/{DEFAULT_PASSWORD} se não existir.")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.exists():
            raise CommandError(f"Arquivo não encontrado: {path}")

        user = self._get_user(opts["user"], opts["create_user"])
        wb = openpyxl.load_workbook(path, data_only=True)

        with db_transaction.atomic():
            # Fresh import: wipe this user's data so re-runs stay clean.
            deleted = Transaction.objects.filter(owner=user).delete()[0]
            if deleted:
                self.stdout.write(f"Removidos {deleted} lançamentos antigos.")

            cards = self._ensure_cards(user)

            tx_count = inst_count = 0
            covered = set()  # (card_name, competence) already detailed by a card sheet
            for sheet_name, card_name in CARD_SHEETS.items():
                if sheet_name not in wb.sheetnames:
                    continue
                t, i, months = self._import_card_sheet(wb[sheet_name], cards[card_name], user)
                tx_count += t
                inst_count += i
                covered |= {(card_name, m) for m in months}

            if "CONTAS" in wb.sheetnames:
                t, i = self._import_contas(wb["CONTAS"], user, cards, covered)
                tx_count += t
                inst_count += i

        self.stdout.write(self.style.SUCCESS(
            f"Importação concluída: {tx_count} lançamentos, {inst_count} parcelas para '{user.username}'."
        ))

    # ------------------------------------------------------------------ #

    def _get_user(self, username, create):
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            if not create and username != DEFAULT_USERNAME:
                raise CommandError(f"Usuário '{username}' não existe (use --create-user).")
            user = User.objects.create_user(username=username, password=DEFAULT_PASSWORD)
            # Force a real password on first login.
            from finance.models import Profile
            Profile.objects.update_or_create(user=user, defaults={"must_change_password": True})
            self.stdout.write(self.style.SUCCESS(
                f"Usuário '{username}' criado (senha temporária: {DEFAULT_PASSWORD}). "
                "Será exigida a troca no primeiro acesso."
            ))
            return user

    def _ensure_cards(self, user):
        cards = {}
        for name in set(CARD_SHEETS.values()):
            cards[name] = Card.objects.get_or_create(owner=user, name=name)[0]
        return cards

    def _import_card_sheet(self, ws, card, user):
        """Each row = a purchase; filled month columns = installments."""
        # Map column index -> competence date from the header row (row 1).
        col_month = {}
        for col in range(2, ws.max_column + 1):
            mn = month_number(ws.cell(row=1, column=col).value)
            if mn:
                col_month[col] = comp(mn)
        if not col_month:
            return 0, 0, set()

        covered_months = set()
        tx_count = inst_count = 0
        for row in range(2, ws.max_row + 1):
            desc = ws.cell(row=row, column=1).value
            if not desc or not str(desc).strip():
                continue  # total rows / blank rows have no description
            desc = str(desc).strip()

            # Collect (competence, amount) for filled month columns.
            entries = []
            for col, competence in col_month.items():
                amount = num(ws.cell(row=row, column=col).value)
                if amount is not None and amount != 0:
                    entries.append((competence, amount))
            if not entries:
                continue
            entries.sort(key=lambda e: e[0])

            # Installment numbering: honour "x/y" if present in the description.
            m = INSTALLMENT_RE.search(desc)
            start_no = int(m.group(1)) if m else 1
            of_total = int(m.group(2)) if m else len(entries)

            total = sum(a for _, a in entries)
            tx = Transaction.objects.create(
                owner=user, kind=Kind.EXPENSE, description=desc, card=card,
                total_amount=total,
                repeat_type=RepeatType.INSTALLMENT if len(entries) > 1 else RepeatType.SINGLE,
                repeat_count=len(entries), first_competence=entries[0][0],
                notes="Importado da planilha", needs_review=True,
            )
            tx_count += 1
            for offset, (competence, amount) in enumerate(entries):
                Installment.objects.create(
                    transaction=tx, owner=user, number=start_no + offset, of_total=of_total,
                    competence_month=competence,
                    due_date=date(competence.year, competence.month, min(card.due_day, 28)) if card.due_day else None,
                    amount=amount,
                )
                inst_count += 1
                covered_months.add(competence)
        return tx_count, inst_count, covered_months

    def _import_contas(self, ws, user, cards, covered):
        """CONTAS: months in 3-column blocks. Bring non-card expenses + income."""
        # Discover month blocks from header row 1.
        blocks = []  # (label_col, competence)
        for col in range(1, ws.max_column + 1):
            mn = month_number(ws.cell(row=1, column=col).value)
            if mn:
                blocks.append((col, comp(mn)))

        tx_count = inst_count = 0
        for label_col, competence in blocks:
            section = None
            for row in range(2, ws.max_row + 1):
                label = ws.cell(row=row, column=label_col).value
                label = str(label).strip() if label else ""
                upper = label.upper()

                if upper == "DESPESAS":
                    section = "E"; continue
                if upper == "RECEITAS":
                    section = "I"; continue
                if upper.startswith("TOTAL") or upper in {"SOBRA", "DIVIDAS"}:
                    section = None; continue
                if not label or section is None:
                    continue

                # Value sits at offset +1 or +2 within the block.
                value = num(ws.cell(row=row, column=label_col + 1).value)
                if value is None:
                    value = num(ws.cell(row=row, column=label_col + 2).value)
                if value is None:
                    continue

                card = None
                if section == "E":
                    card_name = LABEL_TO_CARD.get(upper)
                    if card_name:
                        # Detail sheet already has this card/month -> skip total.
                        if (card_name, competence) in covered:
                            continue
                        card = cards.get(card_name)  # import the total as a card line
                    kind, amount = Kind.EXPENSE, abs(value)
                else:  # income stored as negative in the sheet
                    kind, amount = Kind.INCOME, abs(value)

                if amount == 0:
                    continue
                tx = Transaction.objects.create(
                    owner=user, kind=kind, description=label, card=card,
                    total_amount=amount, repeat_type=RepeatType.SINGLE,
                    repeat_count=1, first_competence=competence,
                    notes="Importado da planilha (CONTAS)", needs_review=True,
                )
                Installment.objects.create(
                    transaction=tx, owner=user, number=1, of_total=1,
                    competence_month=competence, amount=amount,
                )
                tx_count += 1
                inst_count += 1
        return tx_count, inst_count
