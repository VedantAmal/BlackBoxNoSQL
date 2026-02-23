from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from models import db

class User(UserMixin, db.Document):
    """User model for authentication and profile"""
    meta = {'collection': 'users', 'indexes': ['username', 'email']}
    
    # id is automatically created as ObjectId
    username = db.StringField(max_length=80, unique=True, required=True)
    email = db.StringField(max_length=120, unique=True, required=True)
    password_hash = db.StringField(max_length=255, required=True)
    
    # User info
    full_name = db.StringField(max_length=120)
    is_admin = db.BooleanField(default=False)
    is_active = db.BooleanField(default=True)
    
    # Team relationship
    # Use string reference 'Team' to avoid circular import issues during registration
    team = db.ReferenceField('Team', reverse_delete_rule=db.NULLIFY)
    is_team_captain = db.BooleanField(default=False)
    
    # Timestamps
    created_at = db.DateTimeField(default=datetime.utcnow)
    last_login = db.DateTimeField()
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if password matches hash"""
        return check_password_hash(self.password_hash, password)
    
    def get_team(self):
        """Get user's team"""
        return self.team
    
    @property
    def team_id(self):
        """Compatibility property for team_id"""
        return str(self.team.id) if self.team else None

    @property
    def solves(self):
        from models.submission import Solve
        return Solve.objects(user=self)

    @property
    def submissions(self):
        from models.submission import Submission
        return Submission.objects(user=self)

    def get_score(self):
        """Calculate user's total score dynamically (solves - hint costs)"""
        if self.team:
            return self.team.get_score()
        else:
            # Sum solve points
            solve_points = sum([solve.get_current_points() for solve in self.solves])
            
            # Subtract hint costs
            from models.hint import HintUnlock
            hint_costs = HintUnlock.objects(user=self, team=None).sum('cost_paid')
            
            return int(solve_points) - int(hint_costs)
    
    def get_solves_count(self):
        """Get number of challenges solved"""
        return self.solves.filter(challenge__ne=None).count()
    
    def has_solved(self, challenge_id):
        """Check if user has solved a challenge"""
        return self.solves.filter(challenge=challenge_id).first() is not None
    
    def to_dict(self, include_email=False):
        """Convert user to dictionary"""
        data = {
            'id': str(self.id),
            'username': self.username,
            'full_name': self.full_name,
            'is_admin': self.is_admin,
            'team_id': self.team_id,
            'is_team_captain': self.is_team_captain,
            'score': self.get_score(),
            'solves': self.get_solves_count(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_email:
            data['email'] = self.email
        return data
    
    def __repr__(self):
        return f'<User {self.username}>'
