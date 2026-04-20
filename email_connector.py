import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from cryptography.fernet import Fernet
import os
import ssl


class EmailSender:
    def __init__(self, smtp_server="vandewiele-com.mail.protection.outlook.com", smtp_port=25):
        """
        Inizializza il sender email con server e porta SMTP

        Args:
            smtp_server (str): Server SMTP
            smtp_port (int): Porta SMTP (default: 25 per relay server)
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.key = None
        self.encrypted_password = None
        self._key_file = "email_key.key"
        self._credentials_file = "email_credentials.enc"

    def setup_encryption(self):
        if os.path.exists(self._key_file):
            with open(self._key_file, "rb") as key_file:
                self.key = key_file.read()
        else:
            self.key = Fernet.generate_key()
            with open(self._key_file, "wb") as key_file:
                key_file.write(self.key)

    def save_credentials(self, email, password=""):
        """
        Salva solo l'indirizzo email (password non necessaria per relay server)

        Args:
            email (str): Indirizzo email mittente
            password (str): Non utilizzato per relay server
        """
        if not self.key:
            self.setup_encryption()

        f = Fernet(self.key)
        credentials = f"{email}:{password}".encode()
        encrypted_credentials = f.encrypt(credentials)

        with open(self._credentials_file, "wb") as cred_file:
            cred_file.write(encrypted_credentials)

    def load_credentials(self):
        if not os.path.exists(self._credentials_file):
            raise FileNotFoundError("Credenziali non trovate. Usa prima save_credentials()")

        if not self.key:
            self.setup_encryption()

        f = Fernet(self.key)
        with open(self._credentials_file, "rb") as cred_file:
            encrypted_credentials = cred_file.read()

        decrypted_credentials = f.decrypt(encrypted_credentials).decode()
        email, _ = decrypted_credentials.split(":")
        return email

    def send_email(self, to_email, subject, body, is_html=False):
        """
        Invia una email usando il relay server

        Args:
            to_email (str): Indirizzo email destinatario
            subject (str): Oggetto dell'email
            body (str): Corpo dell'email
            is_html (bool): True se il body è in formato HTML
        """
        # Carica l'indirizzo email del mittente
        from_email = self.load_credentials()

        # Crea il messaggio
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject

        # Aggiungi il corpo
        if is_html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        try:
            print(f"Tentativo di connessione a {self.smtp_server}:{self.smtp_port}...")
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.ehlo()

            # Non serve TLS o autenticazione per il relay server interno

            # Invia email
            print("Invio email...")
            server.send_message(msg)
            print("Email inviata con successo!")

            server.quit()
            return True

        except Exception as e:
            print(f"Errore nell'invio dell'email: {str(e)}")
            raise

