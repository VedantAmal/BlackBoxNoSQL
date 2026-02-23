"""
Challenge branching models
Handles multiple flags, prerequisites, and flag-based challenge unlocking
"""

from datetime import datetime
from models import db
import re


class ChallengeFlag(db.Document):
    """Model for multiple flags per challenge with branching support"""
    meta = {'collection': 'challenge_flags'}
    
    challenge = db.ReferenceField('Challenge', required=True, reverse_delete_rule=db.CASCADE)
    
    # Flag details
    flag_value = db.StringField(max_length=255, required=True)
    flag_label = db.StringField(max_length=100)  # User-friendly label for admin
    is_case_sensitive = db.BooleanField(default=True)
    
    # Regex flag support
    is_regex = db.BooleanField(default=False)
    
    # Branching: which challenge does this flag unlock?
    unlocks_challenge = db.ReferenceField('Challenge', reverse_delete_rule=db.NULLIFY)
    
    # Points override (NULL = use challenge's default points)
    points_override = db.IntField()
    
    # Timestamp
    created_at = db.DateTimeField(default=datetime.utcnow)
    
    def check_flag(self, submitted_flag, team_id=None, user_id=None):
        """Check if submitted flag matches this flag
        
        Args:
            submitted_flag: The flag submitted by the user
            team_id: Optional team_id (for future use)
            user_id: Optional user_id (for future use)
            
        Returns:
            bool: True if flag matches, False otherwise
        """
        # Handle regex flags
        if self.is_regex:
            try:
                if self.is_case_sensitive:
                    pattern = re.compile(self.flag_value)
                else:
                    pattern = re.compile(self.flag_value, re.IGNORECASE)
                return pattern.fullmatch(submitted_flag) is not None
            except re.error:
                # Invalid regex pattern, fall back to exact match
                pass
        
        # Standard static flag comparison
        if self.is_case_sensitive:
            return submitted_flag == self.flag_value
        else:
            return submitted_flag.lower() == self.flag_value.lower()
    
    def to_dict(self, include_value=False):
        """Convert to dictionary"""
        data = {
            'id': str(self.id),
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'label': self.flag_label,
            'unlocks_challenge_id': str(self.unlocks_challenge.id) if self.unlocks_challenge else None,
            'points_override': self.points_override,
            'is_case_sensitive': self.is_case_sensitive,
            'is_regex': self.is_regex
        }
        
        if include_value:
            data['flag_value'] = self.flag_value
        
        return data
    
    def __repr__(self):
        return f'<ChallengeFlag {self.id} for Challenge {self.challenge.id}>'


class ChallengePrerequisite(db.Document):
    """Model for challenge prerequisites (must solve A before seeing B)"""
    meta = {
        'collection': 'challenge_prerequisites',
        'indexes': [
            {'fields': ['challenge', 'prerequisite_challenge'], 'unique': True}
        ]
    }
    
    challenge = db.ReferenceField('Challenge', required=True, reverse_delete_rule=db.CASCADE)
    prerequisite_challenge = db.ReferenceField('Challenge', required=True, reverse_delete_rule=db.CASCADE)
    
    # Timestamp
    created_at = db.DateTimeField(default=datetime.utcnow)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'prerequisite_challenge_id': str(self.prerequisite_challenge.id) if self.prerequisite_challenge else None,
            'prerequisite_name': self.prerequisite_challenge.name if self.prerequisite_challenge else None
        }
    
    def __repr__(self):
        return f'<ChallengePrerequisite {self.challenge.id} requires {self.prerequisite_challenge.id}>'


class ChallengeUnlock(db.Document):
    """Model for tracking which challenges were unlocked by which flags"""
    meta = {
        'collection': 'challenge_unlocks',
        'indexes': [
            {'fields': ['user', 'team', 'challenge'], 'unique': True, 'sparse': True}
        ]
    }
    
    user = db.ReferenceField('User', required=True, reverse_delete_rule=db.CASCADE)
    team = db.ReferenceField('Team', reverse_delete_rule=db.CASCADE)
    challenge = db.ReferenceField('Challenge', required=True, reverse_delete_rule=db.CASCADE)
    unlocked_by_flag = db.ReferenceField('ChallengeFlag', required=True, reverse_delete_rule=db.CASCADE)
    
    # Timestamp
    unlocked_at = db.DateTimeField(default=datetime.utcnow)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'user_id': str(self.user.id) if self.user else None,
            'team_id': str(self.team.id) if self.team else None,
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'unlocked_by_flag_id': str(self.unlocked_by_flag.id) if self.unlocked_by_flag else None,
            'unlocked_at': self.unlocked_at.isoformat() if self.unlocked_at else None
        }
    
    def __repr__(self):
        return f'<ChallengeUnlock Challenge:{self.challenge.id} by Flag:{self.unlocked_by_flag.id}>'
