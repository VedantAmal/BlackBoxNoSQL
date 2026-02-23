from datetime import datetime
from models import db

class Submission(db.Document):
    """Submission model for tracking all flag attempts"""
    meta = {'collection': 'submissions', 'indexes': ['user', 'challenge', 'team', 'is_correct', 'submitted_at']}
    
    # Relationships
    user = db.ReferenceField('User', required=True)
    challenge = db.ReferenceField('Challenge', required=True)
    team = db.ReferenceField('Team')
    
    # Submission details
    submitted_flag = db.StringField(max_length=255, required=True)
    is_correct = db.BooleanField(default=False)
    ip_address = db.StringField(max_length=45)
    
    # Timestamp
    submitted_at = db.DateTimeField(default=datetime.utcnow)
    
    def to_dict(self):
        """Convert submission to dictionary"""
        return {
            'id': str(self.id),
            'user_id': str(self.user.id) if self.user else None,
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'team_id': str(self.team.id) if self.team else None,
            'is_correct': self.is_correct,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None
        }
    
    def __repr__(self):
        return f'<Submission {self.id} - User:{self.user.id} Challenge:{self.challenge.id}>'


class Solve(db.Document):
    """Solve model for tracking successful challenge completions"""
    meta = {
        'collection': 'solves', 
        'indexes': [
            'user', 'challenge', 'team', 'solved_at',
            {'fields': ['user', 'challenge'], 'unique': True, 'sparse': True},
            {'fields': ['team', 'challenge'], 'unique': True, 'sparse': True}
        ]
    }
    
    # Relationships
    user = db.ReferenceField('User')
    challenge = db.ReferenceField('Challenge') # None for manual adjustments
    flag = db.ReferenceField('ChallengeFlag') # Which flag was used
    team = db.ReferenceField('Team')
    
    # Solve details
    points_earned = db.IntField(required=True)
    solve_time = db.IntField()
    is_first_blood = db.BooleanField(default=False)
    
    # Timestamp
    solved_at = db.DateTimeField(default=datetime.utcnow)
    
    def get_current_points(self):
        """Get current point value for this solve"""
        if not self.challenge:
            return self.points_earned
        
        # In MongoEngine, accessing self.challenge fetches the document
        challenge = self.challenge
        
        if not challenge.is_dynamic:
            return self.points_earned
        
        from services.scoring import ScoringService
        current_points = ScoringService.calculate_dynamic_points(challenge)
        
        if self.is_first_blood:
            from models.settings import Settings
            first_blood_bonus = Settings.get('first_blood_bonus', 0, type='int')
            current_points += first_blood_bonus
        
        return current_points
    
    def to_dict(self):
        """Convert solve to dictionary"""
        return {
            'id': str(self.id),
            'user_id': str(self.user.id) if self.user else None,
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'team_id': str(self.team.id) if self.team else None,
            'points_earned': self.points_earned,
            'solved_at': self.solved_at.isoformat() if self.solved_at else None
        }
    
    def __repr__(self):
        return f'<Solve {self.id} - User:{self.user.id} Challenge:{self.challenge.id}>'
