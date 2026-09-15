from utils.db import query_db, execute_db
from utils.logger import get_logger

logger = get_logger("notifications")


def create_notification(user_id, title, body, link=None):
    if not user_id or not title:
        return None
    try:
        notif_id = execute_db(
            "INSERT INTO notifications (user_id, title, body, link, is_read, created_at) VALUES (%s, %s, %s, %s, 0, NOW())",
            (user_id, title, body, link)
        )
        logger.info("Notification created for user %s: %s", user_id, title)
        return notif_id
    except Exception as e:
        logger.error("Failed to create notification for user %s: %s", user_id, e)
        return None


def notify_patient(patient_id, title, body, link=None):
    if not patient_id or not title:
        return None

    try:
        pat_id = patient_id["id"] if isinstance(patient_id, dict) else str(patient_id)
        patient = query_db("SELECT linked_user_id FROM patients WHERE id = %s", (pat_id,), one=True)
        if patient and patient.get("linked_user_id"):
            return create_notification(patient["linked_user_id"], title, body, link)
    except Exception as e:
        logger.error("Failed to notify patient %s: %s", patient_id, e)
        return None

    return None
