from flask import Blueprint, jsonify, request, abort
from flask_login import login_required, current_user
from models.notification import Notification
from models.notification_read import NotificationRead
from models import db
from services.websocket import WebSocketService

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api')


@notifications_bp.route('/notifications')
@login_required
def get_notifications():
    """Return recent notifications and user's unread count"""
    notifs = Notification.objects.order_by('-created_at').limit(50)

    # Compute unread count for current user
    read_ids = {nr.notification.id for nr in NotificationRead.objects(user=current_user)}

    notif_dicts = []
    unread = 0
    for n in notifs:
        d = n.to_dict()
        d['read'] = n.id in read_ids
        if not d['read']:
            unread += 1
        notif_dicts.append(d)

    return jsonify({'success': True, 'notifications': notif_dicts, 'unread': unread})


@notifications_bp.route('/notifications/<string:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    """Mark a notification as read for the current user"""
    notif = Notification.objects.get_or_404(id=notif_id)

    existing = NotificationRead.objects(notification=notif, user=current_user).first()
    if not existing:
        nr = NotificationRead(notification=notif, user=current_user)
        nr.save()

    return jsonify({'success': True})


@notifications_bp.route('/notifications/<string:notif_id>/delete', methods=['POST'])
@login_required
def delete_notification(notif_id):
    """Allow admins to delete notifications and notify clients"""
    if not current_user.is_admin:
        return abort(403)

    notif = Notification.objects.get_or_404(id=notif_id)
    notif.delete()

    # Notify connected clients to remove this notification
    try:
        WebSocketService.emit_notification_deleted(str(notif_id))
    except Exception:
        pass

    return jsonify({'success': True})
