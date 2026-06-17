"""Enroll a user in TOTP 2FA for the admin (/chefao).

Creates a confirmed TOTP device and prints the secret + an otpauth URL + an
ASCII QR code, so you can add it to Google Authenticator / Authy. Run again to
rotate the secret.

    python manage.py setup_2fa --user thiago
"""

import base64
import io

import qrcode
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Cadastra/renova o 2FA (TOTP) de um usuário para o admin."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="thiago")

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"Usuário '{opts['user']}' não existe.")

        # Fresh device each run (rotates the secret).
        TOTPDevice.objects.filter(user=user).delete()
        device = TOTPDevice.objects.create(user=user, name="default", confirmed=True)

        secret = base64.b32encode(device.bin_key).decode("utf-8")
        url = device.config_url

        # ASCII QR so you can scan straight from the terminal.
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf)

        self.stdout.write(self.style.SUCCESS(f"2FA cadastrado para '{user.username}'."))
        self.stdout.write("\nEscaneie o QR abaixo no Google Authenticator (ou digite o segredo):\n")
        self.stdout.write(buf.getvalue())
        self.stdout.write(f"Segredo (entrada manual): {secret}")
        self.stdout.write(f"URL (otpauth): {url}\n")
        self.stdout.write("Depois, ao entrar em /chefao, informe usuário, senha e o código de 6 dígitos.")
