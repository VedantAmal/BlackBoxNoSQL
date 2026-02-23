"""
Flag Abuse Tracking Model
Tracks attempts to submit flags that belong to other teams (flag sharing)
"""

from models import db
from datetime import datetime, timedelta


class FlagAbuseAttempt(db.Document):
    """Track flag sharing attempts"""
    meta = {'collection': 'flag_abuse_attempts'}
    
    # Who tried to submit the flag
    user = db.ReferenceField('User', required=True)
    team = db.ReferenceField('Team')
    
    # Which challenge
    challenge = db.ReferenceField('Challenge', required=True)
    
    # The flag they submitted
    submitted_flag = db.StringField(max_length=512, required=True)
    
    # Which team does the flag actually belong to
    actual_team = db.ReferenceField('Team')
    actual_user = db.ReferenceField('User')
    
    # Metadata
    ip_address = db.StringField(max_length=45)
    timestamp = db.DateTimeField(default=datetime.utcnow, required=True)
    
    # Abuse severity (for future use)
    severity = db.StringField(max_length=20, default='warning')  # warning, suspicious, critical
    notes = db.StringField()
    
    @staticmethod
    def analyze_temporal_patterns(challenge_id, submitting_team_id, actual_team_id, time_window_minutes=15):
        """Analyze if there's a pattern of team copying flags from another team
        
        This specifically checks if submitting_team repeatedly copies from actual_team,
        not just any flag sharing behavior.
        
        Args:
            challenge_id: The challenge being submitted
            submitting_team_id: Team submitting the flag
            actual_team_id: Team that owns the flag
            time_window_minutes: Time window to check for recent solves (default 15 mins)
            
        Returns:
            dict: Analysis results with severity and pattern info
        """
        from models.submission import Solve
        
        if not submitting_team_id or not actual_team_id:
            return {'pattern_detected': False, 'severity': 'critical'}
        
        # Check if actual_team solved this challenge recently
        solve = Solve.objects(
            challenge=challenge_id,
            team=actual_team_id
        ).order_by('-solved_at').first()
        
        if not solve:
            # Actual team hasn't solved it yet - this is weird, mark as critical
            return {'pattern_detected': False, 'severity': 'critical'}
        
        # Check if solve was within the time window
        time_since_solve = datetime.utcnow() - solve.solved_at
        if time_since_solve > timedelta(minutes=time_window_minutes):
            # Solve was too long ago - still critical but not pattern-based
            return {'pattern_detected': False, 'severity': 'critical'}
        
        # Flag was submitted within time window after actual team solved!
        # Now check SPECIFICALLY if submitting_team has a pattern with actual_team
        
        # Check how many times submitting_team has copied from actual_team specifically
        targeted_attempts = FlagAbuseAttempt.objects(
            team=submitting_team_id,
            actual_team=actual_team_id
        ).count()
        
        # Get all historical abuse attempts from submitting_team (to any team)
        historical_attempts = FlagAbuseAttempt.objects(
            team=submitting_team_id
        ).count()
        
        # Determine severity based on patterns
        severity = 'critical'  # Default to critical for dynamic flag abuse
        pattern_notes = []
        
        # Time-based severity
        if time_since_solve < timedelta(minutes=5):
            pattern_notes.append(f'Flag submitted within {int(time_since_solve.total_seconds() / 60)} minutes of solve')
        elif time_since_solve < timedelta(minutes=time_window_minutes):
            pattern_notes.append(f'Flag submitted within {int(time_since_solve.total_seconds() / 60)} minutes of solve')
        
        # CRITICAL: Pattern of repeatedly copying from the SAME team
        if targeted_attempts >= 2:
            severity = 'critical'
            pattern_notes.append(f'PATTERN DETECTED: Team has now copied from this same team {targeted_attempts + 1} times')
        elif targeted_attempts >= 1:
            severity = 'critical'
            pattern_notes.append(f'Team has copied from this same team {targeted_attempts + 1} times')
        
        # Escalate if team is a serial offender (copies from many teams)
        if historical_attempts >= 5:
            pattern_notes.append(f'Serial offender: {historical_attempts + 1} total flag sharing attempts')
        elif historical_attempts >= 3:
            pattern_notes.append(f'Multiple violations: {historical_attempts + 1} total flag sharing attempts')
        
        return {
            'pattern_detected': targeted_attempts >= 1,  # Pattern = repeatedly from same team
            'severity': severity,
            'time_since_solve_minutes': int(time_since_solve.total_seconds() / 60),
            'historical_attempts': historical_attempts,
            'targeted_attempts': targeted_attempts,
            'notes': '; '.join(pattern_notes)
        }
    
    @staticmethod
    def get_repeat_offenders(limit=10, min_attempts=3):
        """Get teams/users with most flag abuse attempts
        
        Args:
            limit: Maximum number of results to return
            min_attempts: Minimum number of attempts to be considered
            
        Returns:
            list: List of dicts with team/user info and attempt counts
        """
        # Group by team and count attempts using Aggregation Pipeline
        pipeline = [
            {'$match': {'team': {'$ne': None}}},
            {'$group': {
                '_id': '$team',
                'attempt_count': {'$sum': 1},
                'last_attempt': {'$max': '$timestamp'}
            }},
            {'$match': {'attempt_count': {'$gte': min_attempts}}},
            {'$sort': {'attempt_count': -1}},
            {'$limit': limit}
        ]
        
        team_counts = list(FlagAbuseAttempt.objects.aggregate(*pipeline))
        
        from models.team import Team
        results = []
        for entry in team_counts:
            team_id = entry['_id']
            count = entry['attempt_count']
            last_attempt = entry['last_attempt']
            
            team = Team.objects(id=team_id).first()
            if team:
                results.append({
                    'team_id': str(team.id),
                    'team_name': team.name,
                    'attempt_count': count,
                    'last_attempt': last_attempt
                })
        
        return results
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
            'team_id': self.team_id,
            'team_name': self.team.name if self.team else None,
            'challenge_id': self.challenge_id,
            'challenge_name': self.challenge.name if self.challenge else None,
            'submitted_flag': self.submitted_flag[:50] + '...' if len(self.submitted_flag) > 50 else self.submitted_flag,
            'actual_team_id': self.actual_team_id,
            'actual_team_name': self.actual_team.name if self.actual_team else None,
            'actual_user_id': self.actual_user_id,
            'actual_user_name': self.actual_user.username if self.actual_user else None,
            'ip_address': self.ip_address,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'severity': self.severity,
            'notes': self.notes
        }
    
    def __repr__(self):
        return f'<FlagAbuseAttempt user={self.user_id} challenge={self.challenge_id}>'

    # Convenience properties for templates
    @property
    def user_name(self):
        return self.user.username if self.user else None

    @property
    def team_name(self):
        return self.team.name if self.team else None

    @property
    def actual_team_name(self):
        return self.actual_team.name if self.actual_team else None

    @property
    def actual_user_name(self):
        return self.actual_user.username if self.actual_user else None

    @property
    def challenge_name(self):
        return self.challenge.name if self.challenge else None
