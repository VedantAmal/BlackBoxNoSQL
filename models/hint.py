from datetime import datetime
from models import db

class Hint(db.Document):
    """Hint model for challenge hints with costs"""
    meta = {'collection': 'hints'}
    
    challenge = db.ReferenceField('Challenge', required=True, reverse_delete_rule=db.CASCADE)
    content = db.StringField(required=True)
    cost = db.IntField(default=0)
    order = db.IntField(default=0)
    
    requires_hint = db.ReferenceField('self', reverse_delete_rule=db.NULLIFY)
    
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)
    
    @property
    def unlocks(self):
        return HintUnlock.objects(hint=self)
    
    def is_unlocked_by_user(self, user_id):
        """Check if hint is unlocked by user"""
        # user_id might be string or ObjectId
        return HintUnlock.objects(hint=self, user=user_id).first() is not None
    
    def is_unlocked_by_team(self, team_id):
        """Check if hint is unlocked by team"""
        return HintUnlock.objects(hint=self, team=team_id).first() is not None
    
    def can_unlock(self, user_id=None, team_id=None):
        """Check if user/team can unlock this hint (checks prerequisites)"""
        if not self.requires_hint:
            return (True, None)
        
        prerequisite = self.requires_hint
        
        if team_id:
            prereq_unlocked = prerequisite.is_unlocked_by_team(team_id)
        else:
            prereq_unlocked = prerequisite.is_unlocked_by_user(user_id)
        
        if not prereq_unlocked:
            return (False, f'You must unlock Hint #{prerequisite.order} first')
        
        return (True, None)
    
    def to_dict(self, include_content=False):
        """Convert hint to dictionary"""
        data = {
            'id': str(self.id),
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'cost': self.cost,
            'order': self.order,
            'requires_hint_id': str(self.requires_hint.id) if self.requires_hint else None,
        }
        
        if include_content:
            data['content'] = self.content
        
        return data
    
    def __repr__(self):
        return f'<Hint {self.id} for Challenge {self.challenge.id}>'


class HintUnlock(db.Document):
    """Track which hints have been unlocked by which users/teams"""
    meta = {'collection': 'hint_unlocks'}
    
    hint = db.ReferenceField('Hint', required=True, reverse_delete_rule=db.CASCADE)
    user = db.ReferenceField('User', required=True, reverse_delete_rule=db.CASCADE)
    team = db.ReferenceField('Team', reverse_delete_rule=db.CASCADE)
    cost_paid = db.IntField(required=True)
    
    # Timestamps
    unlocked_at = db.DateTimeField(default=datetime.utcnow)
    
    def __repr__(self):
        return f'<HintUnlock {self.hint.id} by User {self.user.id}>'
