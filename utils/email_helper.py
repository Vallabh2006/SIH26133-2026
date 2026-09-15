import os
import re
import logging
from flask import current_app
from mailjet_rest import Client

from utils.logger import get_logger
logger = get_logger("email")

def get_mailjet_credentials():
    api_key = (
        os.getenv("MAIL_USERNAME")
        or os.getenv("MJ_APIKEY_PUBLIC")
        or os.getenv("MAILJET_API_KEY")
    )
    api_secret = (
        os.getenv("MAIL_PASSWORD")
        or os.getenv("MJ_APIKEY_PRIVATE")
        or os.getenv("SMTP_PASSWORD")
    )
    sender_email = (
        os.getenv("MAIL_DEFAULT_SENDER")
        or os.getenv("MJ_SENDER_EMAIL")
        or os.getenv("SMTP_EMAIL")
    )
    sender_name = os.getenv("MAIL_SENDER_NAME", "Anvaya Vistara")
    return api_key, api_secret, sender_email, sender_name


def send_email(to: str, subject: str, body: str, html_body: str = None, recipient_name: str = "User") -> bool:
    try:
        if current_app and current_app.config.get('TESTING'):
            logger.info(f"Suppressed outgoing email during testing to {to}: {subject}")
            return True
    except Exception:
        pass

    if not to or not subject or not body:
        logger.warning("Recipient email, subject, or body is required.")
        return False

    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(email_pattern, to.strip()):
        logger.warning(f"Invalid recipient email address: {to}")
        return False

    api_key, api_secret, sender_email, sender_name = get_mailjet_credentials()

    if not api_key or not api_secret:
        logger.warning("Mailjet API credentials not configured in environment.")
        return False

    if not sender_email:
        logger.warning("Sender email (MAIL_DEFAULT_SENDER) not configured in environment.")
        return False

    try:
        mailjet = Client(auth=(api_key, api_secret), version='v3.1')
        data = {
            'Messages': [
                {
                    "From": {
                        "Email": sender_email,
                        "Name": sender_name
                    },
                    "To": [
                        {
                            "Email": to.strip(),
                            "Name": recipient_name or "User"
                        }
                    ],
                    "Subject": subject,
                    "TextPart": body,
                    "HTMLPart": html_body or f"<p>{body}</p>"
                }
            ]
        }
        result = mailjet.send.create(data=data)
        if result.status_code in [200, 201]:
            res = result.json()
            messages = res.get('Messages', [])
            if messages and messages[0].get('Status') == 'success':
                return True
            logger.error(f"Mailjet response status not success: {res}")
            return False
        else:
            logger.error(f"Mailjet API returned error code {result.status_code}: {result.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send email via Mailjet to {to}: {e}")
        return False


def mask_email(email_str: str) -> str:
    if not email_str or '@' not in email_str:
        return email_str or ''
    parts = email_str.split('@', 1)
    user_part = parts[0]
    domain_part = parts[1]

    if len(user_part) <= 2:
        masked_user = user_part[0] + '***'
    elif len(user_part) <= 5:
        masked_user = user_part[0] + ('*' * (len(user_part) - 2)) + user_part[-1]
    else:
        masked_user = user_part[:2] + ('*' * (len(user_part) - 3)) + user_part[-1]

    domain_subparts = domain_part.split('.', 1)
    if len(domain_subparts) == 2:
        dom_name = domain_subparts[0]
        dom_ext = domain_subparts[1]
        if len(dom_name) <= 2:
            masked_dom = dom_name[0] + '***'
        elif len(dom_name) == 3:
            masked_dom = dom_name[0] + '*' + dom_name[-1]
        else:
            masked_dom = dom_name[0] + ('*' * (len(dom_name) - 2)) + dom_name[-1]
        return f"{masked_user}@{masked_dom}.{dom_ext}"
    else:
        return f"{masked_user}@{domain_part}"


def send_otp_email(to_email: str, full_name: str, otp_code: str) -> bool:
    subject = f"Anvaya Vistara Verification Code: {otp_code}"
    user_display = full_name or 'User'

    text_body = f"Hello {user_display},\n\nYour 6-digit verification code is: {otp_code}\n\nThis code will expire in 10 minutes.\n\nBest regards,\nAnvaya Vistara"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
    <div style="max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 28px;">
        <h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Anvaya Vistara</h2>
        <p style="color: #334155; font-size: 15px;">Hello {user_display},</p>
        <p style="color: #475569; font-size: 14px;">Here is your single-use verification code:</p>
        <div style="background-color: #f1f5f9; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
            <span style="font-size: 28px; font-weight: 700; letter-spacing: 6px; color: #1e40af;">{otp_code}</span>
        </div>
        <p style="color: #64748b; font-size: 13px;">This code expires in 10 minutes. If you did not request this, please disregard this email.</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 12px; margin: 0;">Anvaya Vistara Healthcare Network</p>
    </div>
</body>
</html>"""

    return send_email(to_email, subject, text_body, html_body, recipient_name=user_display)


def send_password_reset_email(to_email: str, full_name: str, otp_code: str) -> bool:
    subject = f"Anvaya Vistara Password Reset: {otp_code}"
    user_display = full_name or 'User'

    text_body = f"Hello {user_display},\n\nYour password reset code is: {otp_code}\n\nThis code will expire in 10 minutes.\n\nBest regards,\nAnvaya Vistara"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
    <div style="max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 28px;">
        <h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Anvaya Vistara</h2>
        <p style="color: #334155; font-size: 15px;">Hello {user_display},</p>
        <p style="color: #475569; font-size: 14px;">We received a request to reset your password. Your 6-digit confirmation code is:</p>
        <div style="background-color: #f1f5f9; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
            <span style="font-size: 28px; font-weight: 700; letter-spacing: 6px; color: #1e40af;">{otp_code}</span>
        </div>
        <p style="color: #64748b; font-size: 13px;">This code expires in 10 minutes. If you did not make this request, you can safely ignore this message.</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 12px; margin: 0;">Anvaya Vistara Healthcare Network</p>
    </div>
</body>
</html>"""

    return send_email(to_email, subject, text_body, html_body, recipient_name=user_display)


def send_email_change_otp(to_new_email: str, full_name: str, otp_code: str) -> bool:
    subject = f"Anvaya Vistara Email Update Code: {otp_code}"
    user_display = full_name or 'User'

    text_body = f"Hello {user_display},\n\nYour verification code to update your registered email address is: {otp_code}\n\nThis code expires in 10 minutes.\n\nBest regards,\nAnvaya Vistara"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
    <div style="max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 28px;">
        <h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Anvaya Vistara</h2>
        <p style="color: #334155; font-size: 15px;">Hello {user_display},</p>
        <p style="color: #475569; font-size: 14px;">Your verification code to update your registered email address is:</p>
        <div style="background-color: #f1f5f9; border-radius: 6px; padding: 16px; text-align: center; margin: 20px 0;">
            <span style="font-size: 28px; font-weight: 700; letter-spacing: 6px; color: #1e40af;">{otp_code}</span>
        </div>
        <p style="color: #64748b; font-size: 13px;">This code expires in 10 minutes.</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 12px; margin: 0;">Anvaya Vistara Healthcare Network</p>
    </div>
</body>
</html>"""

    return send_email(to_new_email, subject, text_body, html_body, recipient_name=user_display)


def send_staff_invite_email(to_email: str, full_name: str = None, invite_link: str = None, role: str = None, **kwargs) -> bool:
    link = invite_link or kwargs.get('invite_url') or ''
    role_name = role or kwargs.get('role_title') or 'Staff Member'
    center_name = kwargs.get('center_name') or 'Anvaya Vistara Healthcare Network'
    username = kwargs.get('username')
    temp_password = kwargs.get('temp_password')
    subject = "Anvaya Vistara: Staff Account Invitation"
    user_display = full_name or 'Staff Member'

    credentials_text = ""
    credentials_html = ""
    if username or temp_password:
        credentials_text = f"\nYour initial credentials:\nUsername: {username or 'N/A'}\nTemporary Password: {temp_password or 'Set during activation'}\n"
        credentials_html = f"""
        <div style="background-color: #f1f5f9; border-radius: 6px; padding: 14px; margin: 16px 0;">
            <p style="margin: 0 0 6px 0; font-size: 13px;"><strong>Username:</strong> {username or 'N/A'}</p>
            <p style="margin: 0; font-size: 13px;"><strong>Temporary Password:</strong> {temp_password or 'Set during activation'}</p>
        </div>
        """

    text_body = f"Hello {user_display},\n\nYou have been invited to join {center_name} as a {role_name}.{credentials_text}\nActivate your account using this link:\n{link}\n\nBest regards,\nAnvaya Vistara"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
    <div style="max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 28px;">
        <h2 style="color: #0f172a; margin-top: 0; font-size: 20px;">Anvaya Vistara</h2>
        <p style="color: #334155; font-size: 15px;">Hello {user_display},</p>
        <p style="color: #475569; font-size: 14px;">You have been invited to join <strong>{center_name}</strong> as a <strong>{role_name}</strong>.</p>
        {credentials_html}
        <p style="margin: 24px 0;"><a href="{link}" style="display: inline-block; background: #1e40af; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">Activate Account</a></p>
        <p style="font-size: 12px; color: #64748b;">If the button above does not work, copy and paste this URL into your browser:<br>{link}</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 12px; margin: 0;">Anvaya Vistara Healthcare Network</p>
    </div>
</body>
</html>"""

    return send_email(to_email, subject, text_body, html_body, recipient_name=user_display)
