from datetime import datetime
from models import db

class Team(db.Document):
    """Team model for collaborative play"""
    meta = {'collection': 'teams', 'indexes': ['name', 'invite_code']}
    
    name = db.StringField(max_length=100, unique=True, required=True)
    invite_code = db.StringField(max_length=8, unique=True, required=True)
    password_hash = db.StringField(max_length=255)
    
    # Team info
    affiliation = db.StringField(max_length=120)
    country = db.StringField(max_length=50)
    website = db.StringField(max_length=200)
    is_active = db.BooleanField(default=True)
    
    # Captain
    # Use string reference 'User' to avoid circular import issues
    # reverse_delete_rule removed here to avoid circular dependency during registration
    # It is re-added in models/__init__.py
    captain = db.ReferenceField('User')
    
    # Timestamps
    created_at = db.DateTimeField(default=datetime.utcnow)
    
    @property
    def members(self):
        from models.user import User
        return User.objects(team=self)

    @property
    def solves(self):
        from models.submission import Solve
        return Solve.objects(team=self)
    
    @property
    def captain_id(self):
        return str(self.captain.id) if self.captain else None

    def get_score(self):
        """Calculate team's total score dynamically (solves - hint costs)"""
        # Sum solve points
        solve_points = sum([solve.get_current_points() for solve in self.solves])
        
        # Subtract hint costs
        from models.hint import HintUnlock
        hint_costs = HintUnlock.objects(team=self).sum('cost_paid')
        
        return int(solve_points) - int(hint_costs)
    
    def get_solves_count(self):
        """Get number of challenges solved by team"""
        return self.solves.filter(challenge__ne=None).count()
    
    def get_members(self):
        """Get all team members"""
        from models.user import User
        return User.objects(team=self)
    
    def get_member_count(self):
        """Get number of team members"""
        return self.members.count()
    
    def has_solved(self, challenge_id):
        """Check if team has solved a challenge"""
        return self.solves.filter(challenge=challenge_id).first() is not None
    
    def get_last_solve_time(self):
        """Get the timestamp of the last solve"""
        last_solve = self.solves.order_by('-solved_at').first()
        return last_solve.solved_at if last_solve else None
    
    def can_join(self, max_size=4):
        """Check if team has space for new members"""
        return self.get_member_count() < max_size
    
    def set_password(self, password):
        """Hash and set team password"""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password) if password else None
    
    def check_password(self, password):
        """Check if password matches hash"""
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return True  # No password set
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self, include_members=False, include_invite_code=False):
        """Convert team to dictionary"""
        data = {
            'id': str(self.id),
            'name': self.name,
            'affiliation': self.affiliation,
            'country': self.country,
            'website': self.website,
            'captain_id': self.captain_id,
            'score': self.get_score(),
            'solves': self.get_solves_count(),
            'member_count': self.get_member_count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'has_password': bool(self.password_hash)
        }
        if include_invite_code:
            data['invite_code'] = self.invite_code
        if include_members:
            data['members'] = [m.to_dict() for m in self.get_members()]
        return data
    
    @staticmethod
    def generate_invite_code():
        """Generate a unique 8-character invite code"""
        import string
        import random
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not Team.objects(invite_code=code).first():
                return code
    
    def __repr__(self):
        return f'<Team {self.name}>'


# Import Solve here to avoid circular import
from models.submission import Solve
