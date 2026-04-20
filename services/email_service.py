import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from email_connector import EmailSender

logger = logging.getLogger(__name__)


class EmailService:
    """
    Wrapper per l'invio email che estende EmailSender (limitato al solo testo)
    con:
      - allegati (lista di tuple (filename, bytes, mimetype))
      - immagini inline richiamate dal corpo HTML via 'cid:<cid>'

    Il mittente viene ricavato da email_credentials.enc (cifrato con la chiave
    email_key.key). Se il file non esiste, si ricade sulle stesse credenziali
    gia' usate in utils.py.
    """

    DEFAULT_SENDER_EMAIL = "Accounting@Eutron.it"
    DEFAULT_SENDER_PASSWORD = "9jHgFhSs7Vf+"

    def __init__(
        self,
        base_dir,
        smtp_server: str = "vandewiele-com.mail.protection.outlook.com",
        smtp_port: int = 25,
        timeout: int = 30,
    ):
        self.base_dir = Path(base_dir)
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.timeout = timeout
        self._sender_email: Optional[str] = None

    def _ensure_credentials(self) -> str:
        if self._sender_email:
            return self._sender_email
        helper = EmailSender(self.smtp_server, self.smtp_port)
        creds_file = self.base_dir / 'email_credentials.enc'
        if not creds_file.exists():
            helper.save_credentials(self.DEFAULT_SENDER_EMAIL, self.DEFAULT_SENDER_PASSWORD)
        self._sender_email = helper.load_credentials()
        return self._sender_email

    def send(
        self,
        recipients: List[str],
        subject: str,
        html_body: str,
        inline_images: Optional[Dict[str, bytes]] = None,
        attachments: Optional[List[Tuple[str, bytes, Optional[str]]]] = None,
    ) -> bool:
        """
        Invia una email HTML. Ritorna True se riesce.

        inline_images: {cid: png_bytes}  -> richiamabili con <img src='cid:<cid>'>
        attachments:   [(filename, data_bytes, mimetype), ...]
        """
        if not recipients:
            logger.warning("EmailService.send: recipients vuoto; email non inviata.")
            return False

        from_email = self._ensure_credentials()

        msg = MIMEMultipart('mixed')
        msg['From'] = from_email
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = subject

        # HTML body (+ eventuali immagini inline richiamate da cid:<id>)
        if inline_images:
            related = MIMEMultipart('related')
            related.attach(MIMEText(html_body, 'html', 'utf-8'))
            for cid, img_bytes in inline_images.items():
                img = MIMEImage(img_bytes)
                img.add_header('Content-ID', f'<{cid}>')
                img.add_header('Content-Disposition', 'inline', filename=f'{cid}.png')
                related.attach(img)
            msg.attach(related)
        else:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        # Allegati
        if attachments:
            for filename, data, mimetype in attachments:
                mt = mimetype or 'application/octet-stream'
                maintype, _, subtype = mt.partition('/')
                part = MIMEBase(maintype or 'application', subtype or 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filename}"',
                )
                msg.attach(part)

        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=self.timeout)
            try:
                server.ehlo()
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            logger.info(
                f"Email inviata a {len(recipients)} destinatari. "
                f"Subject: '{subject}'. "
                f"Inline: {len(inline_images) if inline_images else 0}, "
                f"Attach: {len(attachments) if attachments else 0}."
            )
            return True
        except Exception as e:
            logger.error(f"Errore invio email: {e}")
            return False
