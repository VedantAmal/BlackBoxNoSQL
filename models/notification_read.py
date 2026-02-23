from datetime import datetime
from models import db


class NotificationRead(db.Document):
    meta = {
        'collection': 'notification_reads',
        'indexes': [
            {'fields': ['notification', 'user'], 'unique': True}
        ]
    }

    notification = db.ReferenceField('Notification', required=True, reverse_delete_rule=db.CASCADE)
    user = db.ReferenceField('User', required=True, reverse_delete_rule=db.CASCADE)
    read_at = db.DateTimeField(default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': str(self.id),
            'notification_id': str(self.notification.id) if self.notification else None,
            'user_id': str(self.user.id) if self.user else None,
            'read_at': self.read_at.isoformat() if self.read_at else None
        }
