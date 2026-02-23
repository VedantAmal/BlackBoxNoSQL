from datetime import datetime
from models import db


class Notification(db.Document):
	meta = {'collection': 'notifications'}

	title = db.StringField(max_length=255, required=True)
	body = db.StringField(required=True)
	created_at = db.DateTimeField(default=datetime.utcnow)
	sent_by = db.ReferenceField('User', reverse_delete_rule=db.NULLIFY)
	play_sound = db.BooleanField(default=True, required=True)

	def to_dict(self):
		return {
			'id': str(self.id),
			'title': self.title,
			'body': self.body,
			'created_at': self.created_at.isoformat() if self.created_at else None,
			'sent_by': str(self.sent_by.id) if self.sent_by else None,
			'play_sound': bool(self.play_sound)
		}
