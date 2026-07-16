import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """
    Отправляет email сообщение пользователю.
    Если SMTP настройки в .env не заданы, записывает письмо в локальный файл для отладки.
    """
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = os.environ.get('SMTP_PORT', '587')
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    smtp_from = os.environ.get('SMTP_FROM') or smtp_user

    # Всегда логируем отправку в файл для тестировщиков
    debug_dir = os.path.join(os.getcwd(), 'debug_output')
    os.makedirs(debug_dir, exist_ok=True)
    debug_file_path = os.path.join(debug_dir, 'last_sent_email.html')
    
    try:
        with open(debug_file_path, 'w', encoding='utf-8') as f:
            f.write(f"<!-- To: {to_email} -->\n<!-- Subject: {subject} -->\n{html_content}")
        logger.info(f"Email template written to debug file: {debug_file_path}")
    except Exception as e:
        logger.warning(f"Could not write debug email file: {e}")

    # Если SMTP не настроен, выходим с имитацией успешной отправки
    if not smtp_host or not smtp_user or not smtp_password:
        logger.info("SMTP is not configured in .env. Falling back to local file simulation.")
        print(f"\n[EMAIL SIMULATION] Отправлено на {to_email}\nТема: {subject}\nФайл: {debug_file_path}\n")
        return True

    # Настройка сообщения
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_from
    msg['To'] = to_email

    if text_content:
        msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
        
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Email successfully sent to {to_email} via SMTP")
        return True
    except Exception as e:
        logger.error(f"Failed to send email via SMTP to {to_email}: {e}", exc_info=True)
        return False
