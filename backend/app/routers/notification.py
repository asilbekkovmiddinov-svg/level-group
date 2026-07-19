from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.notification import NotificationResponse, ReadAllResponse, UnreadCountResponse
from app.services import notifications


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationResponse])
def notification_list(current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return notifications.list_notifications(db, current_user.telegram_id)


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return {"unread_count": notifications.count_unread(db, current_user.telegram_id)}


@router.post("/read-all", response_model=ReadAllResponse)
def read_all(current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return notifications.mark_all_read(db, current_user.telegram_id)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def read_notification(notification_id: int, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return notifications.mark_read(db, notification_id, current_user.telegram_id)


@router.post("/{notification_id}/click", response_model=NotificationResponse)
def click_notification(notification_id: int, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return notifications.mark_clicked(db, notification_id, current_user.telegram_id)


@router.delete("/{notification_id}", response_model=NotificationResponse)
def delete_notification(notification_id: int, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return notifications.dismiss(db, notification_id, current_user.telegram_id)
