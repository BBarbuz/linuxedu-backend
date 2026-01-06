import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

logger = logging.getLogger(__name__)

class EmailService:
    
    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL
        self.from_name = settings.SMTP_FROM_NAME
    
    def send_password_email(self, to_email: str, username: str, password: str) -> bool:
        try:
            subject = f"Twoje konto LinuxEdu - Dane Logowania"
            
            html_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; padding: 20px;">
                        <h2 style="color: #0066cc;">Witaj {username}!</h2>
                        
                        <p>Twoje konto na platformie <strong>LinuxEdu</strong> zostało pomyślnie utworzone.</p>
                        
                        <div style="background-color: #f5f5f5; border-left: 4px solid #0066cc; padding: 15px; margin: 20px 0;">
                            <p><strong>Dane logowania:</strong></p>
                            <p><strong>Nazwa użytkownika:</strong> <code>{username}</code></p>
                            <p><strong>Hasło:</strong> <code style="background: #e8e8e8; padding: 5px 10px; border-radius: 4px;">{password}</code></p>
                        </div>
                        
                        <p style="color: #d9534f;"><strong>⚠️ Ważne:</strong></p>
                        <ul>
                            <li>Możesz zalogować się na platformie za pomocą tych danych</li>
                            <li>Nie udostępniaj tego hasła innym osobom</li>
                            <li>Wiadomość zawiera poufne informacje - zachowaj ją w bezpiecznym miejscu</li>
                        </ul>
                        
                        <p>W razie pytań, skontaktuj się z administratorem.</p>
                        
                        <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                        <p style="font-size: 12px; color: #999;">
                            © 2026 LinuxEdu Platform | Wiadomość automatyczna - nie odpowiadaj na ten mail
                        </p>
                    </div>
                </body>
            </html>
            """

            return self._send_smtp(to_email, subject, html_body)
            
        except Exception as e:
            logger.error(f"❌ Mail sending error to {to_email}: {e}")
            return False
    
    def _send_smtp(self, to_email: str, subject: str, html_body: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email
            
            msg.attach(MIMEText(html_body, "html"))
            
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            logger.info(f"✅ Mail sent to {to_email}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error(f"❌ Auth error SMTP.")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ mail sent error: {e}")
            return False

# Singleton
_email_service = None

def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
