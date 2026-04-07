"""
Create in-app notifications and optionally send email when order completes or fails.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import text

from common.db_engine import get_engine as _get_engine

logger = logging.getLogger("ptm-workers.notifications")


def _get_user_for_order(order_id: int) -> tuple[int | None, str | None, bool]:
    """Return (user_id, email, email_notifications_enabled) for the order's run_by_user. None if no user."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT u.id, u.email, COALESCE(u.email_notifications_enabled, 1)
                    FROM orders o
                    JOIN users u ON u.id = COALESCE(o.run_by_user_id, o.user_id)
                    WHERE o.id = :order_id AND COALESCE(o.run_by_user_id, o.user_id) IS NOT NULL
                """),
                {"order_id": order_id},
            ).fetchone()
        if row:
            return (int(row[0]), str(row[1]) if row[1] else None, bool(row[2]))
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to get user for notification: {e}")
    return (None, None, False)


def _get_order_info(order_id: int) -> tuple[str, str]:
    """Return (order_code, project_name) for the order."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT order_code, project_name FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            ).fetchone()
        if row:
            return (row[0] or "", row[1] or "")
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to get order info: {e}")
    return ("", "")


def _insert_notification(user_id: int, order_id: int, ntype: str, title: str, message: str | None = None):
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO notifications (user_id, order_id, notification_type, title, message)
                    VALUES (:user_id, :order_id, :ntype, :title, :message)
                """),
                {
                    "user_id": user_id,
                    "order_id": order_id,
                    "ntype": ntype,
                    "title": title,
                    "message": (message or "")[:2000],
                },
            )
            conn.commit()
        logger.info(f"[Order {order_id}] Notification created for user {user_id}: {ntype}")
    except Exception as e:
        logger.warning(f"[Order {order_id}] Failed to insert notification: {e}")


def _send_email(to_email: str, subject: str, body_text: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        logger.debug("SMTP_HOST not configured, skipping email")
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", "noreply@ptm-platform.local")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        with smtplib.SMTP(host, port) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, [to_email], msg.as_string())
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send email to {to_email}: {e}")
        return False


def notify_order_status(order_id: int, status: str, error_message: str | None = None):
    """
    Create in-app notification and optionally send email when order completes or fails.
    status: 'completed' or 'failed'
    """
    user_id, email, email_enabled = _get_user_for_order(order_id)
    if user_id is None:
        logger.debug(f"[Order {order_id}] No user to notify (run_by_user_id/user_id is null)")
        return

    order_code, project_name = _get_order_info(order_id)
    display_name = project_name or order_code or f"Order #{order_id}"

    if status == "completed":
        ntype = "order_completed"
        title = f"분석 완료: {display_name}"
        message = f"주문 '{display_name}'의 분석이 완료되었습니다."
        email_subject = f"[PTM Platform] 분석 완료: {display_name}"
        email_body = f"PTM Platform 알림\n\n주문 '{display_name}'의 분석이 완료되었습니다.\n\n주문 코드: {order_code}"
    else:
        ntype = "order_failed"
        err = (error_message or "Unknown error")[:500]
        title = f"분석 실패: {display_name}"
        message = f"주문 '{display_name}'의 분석이 실패했습니다.\n{err}"
        email_subject = f"[PTM Platform] 분석 실패: {display_name}"
        email_body = f"PTM Platform 알림\n\n주문 '{display_name}'의 분석이 실패했습니다.\n\n오류: {err}"

    # In-app notification: always create
    _insert_notification(user_id, order_id, ntype, title, message)

    # Email: only if user has it enabled
    if email_enabled and email:
        _send_email(email, email_subject, email_body)
