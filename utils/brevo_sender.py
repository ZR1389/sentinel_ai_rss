"""
Brevo (formerly Sendinblue) email sender for trial and transactional emails.

Uses Brevo API v3 to send emails via HTTP API instead of SMTP.
Suitable for trial reminders, verification emails, and notifications.
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Brevo configuration from environment
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
BREVO_SENDER_EMAIL = os.getenv('BREVO_SENDER_EMAIL', 'info@zikarisk.com')
BREVO_SENDER_NAME = os.getenv('BREVO_SENDER_NAME', 'Zika Risk')
BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'

def send_brevo_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None
) -> bool:
    """
    Send email via Brevo API.
    
    Args:
        to_email: Recipient email address
        to_name: Recipient name
        subject: Email subject
        html_content: HTML email body
        from_email: Sender email (defaults to BREVO_SENDER_EMAIL)
        from_name: Sender name (defaults to BREVO_SENDER_NAME)
    
    Returns:
        True if email sent successfully, False otherwise
    """
    if not BREVO_API_KEY:
        logger.error("BREVO_API_KEY not configured")
        return False
    
    from_email = from_email or BREVO_SENDER_EMAIL
    from_name = from_name or BREVO_SENDER_NAME
    
    headers = {
        'accept': 'application/json',
        'api-key': BREVO_API_KEY,
        'content-type': 'application/json'
    }
    
    payload = {
        'sender': {
            'name': from_name,
            'email': from_email
        },
        'to': [
            {
                'email': to_email,
                'name': to_name
            }
        ],
        'subject': subject,
        'htmlContent': html_content
    }
    
    try:
        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=10)
        
        if response.status_code in [200, 201]:
            logger.info(f"Email sent successfully to {to_email} via Brevo")
            return True
        else:
            logger.error(f"Brevo API error: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"Brevo API timeout sending to {to_email}")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Brevo API request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email via Brevo: {e}")
        return False

def send_trial_email_brevo(
    user_email: str,
    subject: str,
    html_body: str
) -> bool:
    """
    Send trial-related email via Brevo.
    Wrapper for send_brevo_email with trial-specific defaults.
    
    Args:
        user_email: User's email address
        subject: Email subject
        html_body: HTML email content
    
    Returns:
        True if sent successfully
    """
    # Extract name from email (simple fallback)
    user_name = user_email.split('@')[0].capitalize()
    
    return send_brevo_email(
        to_email=user_email,
        to_name=user_name,
        subject=subject,
        html_content=html_body
    )

__all__ = ['send_brevo_email', 'send_trial_email_brevo']
