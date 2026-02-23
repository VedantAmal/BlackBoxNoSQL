from datetime import datetime
from models import db
import json

class Challenge(db.Document):
    """Challenge model for CTF problems"""
    meta = {'collection': 'challenges', 'indexes': ['name', 'category', 'act']}
    
    name = db.StringField(max_length=100, required=True, unique=True)
    description = db.StringField(required=True)
    category = db.StringField(max_length=50, required=True)
    act = db.StringField(max_length=20, default='ACT I')
    
    # Challenge content
    flag = db.StringField(max_length=255, required=True)
    flag_case_sensitive = db.BooleanField(default=True)
    
    # Files and resources
    # Storing as lists/dicts natively in Mongo
    files = db.ListField(db.StringField()) 
    images = db.ListField(db.StringField())
    hints = db.ListField(db.DictField())
    connection_info = db.StringField(max_length=500)
    
    # Docker container settings
    docker_enabled = db.BooleanField(default=False)
    docker_image = db.StringField(max_length=256)
    docker_connection_info = db.StringField(max_length=512)
    docker_flag_path = db.StringField(max_length=256)
    detect_regex_sharing = db.BooleanField(default=False)
    
    # Scoring
    initial_points = db.IntField(required=True, default=500)
    minimum_points = db.IntField(required=True, default=50)
    decay_solves = db.IntField(required=True, default=30)
    
    # Challenge state
    is_visible = db.BooleanField(default=True)
    is_hidden = db.BooleanField(default=False)
    unlock_mode = db.StringField(max_length=20, default='none')
    unlocks_act = db.StringField(max_length=20)
    is_enabled = db.BooleanField(default=True)
    is_dynamic = db.BooleanField(default=True)
    requires_team = db.BooleanField(default=False)
    
    # Metadata
    author = db.StringField(max_length=100)
    difficulty = db.StringField(max_length=20)
    max_attempts = db.IntField(default=0)  # Max attempts per team/user (0=unlimited)
    
    # Timestamps
    created_at = db.DateTimeField(default=datetime.utcnow)
    updated_at = db.DateTimeField(default=datetime.utcnow)

    
    def get_current_points(self):
        """Calculate current points based on number of solves"""
        if not self.is_dynamic:
            return self.initial_points
        
        # Import here to avoid circular imports
        from models.submission import Solve
        solve_count = Solve.objects(challenge=self).count()
        
        if solve_count == 0:
            return self.initial_points
        
        # Import here to avoid circular imports
        import math
        from flask import current_app
        from models.settings import Settings
        
        if solve_count >= self.decay_solves:
            return self.minimum_points
        
        # Get decay function from Settings or config
        decay_function = Settings.get('decay_function', 'string')
        if not decay_function:
            decay_function = current_app.config.get('DECAY_FUNCTION', 'logarithmic')
        
        max_points = self.initial_points
        min_points = self.minimum_points
        decay = self.decay_solves
        
        if decay_function == 'parabolic':
            # Parabolic decay (CTFd-style)
            # Formula: value = (((minimum - initial) / (decay²)) * (solves²)) + initial
            points = (((min_points - max_points) / (decay ** 2)) * (solve_count ** 2)) + max_points
            points = math.ceil(points)
        else:
            # Logarithmic decay (default)
            # Smooth, gradual decrease
            points = max_points - (max_points - min_points) * \
                     (math.log(solve_count + 1) / math.log(decay + 1))
            points = int(points)
        
        return max(points, min_points)
    
    def get_solves_count(self):
        """Get number of solves (excludes manual adjustments)"""
        from models.submission import Solve
        return Solve.objects(challenge=self).count()
    
    def get_submissions_count(self):
        """Get total number of submissions"""
        from models.submission import Submission
        return Submission.objects(challenge=self).count()
    
    def check_flag(self, submitted_flag, team_id=None, user_id=None):
        """Check if submitted flag is correct (checks all flags for this challenge)
        
        Args:
            submitted_flag: The flag string submitted by the user
            team_id: Optional team_id for dynamic flag validation
            user_id: Optional user_id for dynamic flag validation (when not in a team)
        
        Returns:
            Flag object if match found, True for legacy flags, or None if no match
        """
        from models.branching import ChallengeFlag
        from services.cache import cache_service
        
        # Get all flags for this challenge
        flags = ChallengeFlag.objects(challenge=self)
        
        # Check each flag (pass team_id and user_id for template-based flags)
        for flag in flags:
            if flag.check_flag(submitted_flag, team_id=team_id, user_id=user_id):
                return flag  # Return the matching flag object
        
        # Check dynamic flags if docker is enabled
        if self.docker_enabled and (team_id or user_id):
            # Build the cache key for this team/user's dynamic flag
            if team_id:
                team_part = f'team_{team_id}'
            elif user_id:
                team_part = f'user_{user_id}'
            else:
                team_part = None
            
            if team_part:
                cache_key = f"dynamic_flag_mapping:{self.id}:{team_part}"
                expected_flag = cache_service.get(cache_key)
                
                if expected_flag and submitted_flag == expected_flag:
                    # Return a lightweight Flag-like object instead of boolean True.
                    # Downstream code expects an object with certain attributes
                    # (e.g., id, is_regex, is_case_sensitive, flag_value, points_override,
                    # unlocks_challenge_id). Returning a small object prevents
                    # AttributeError/TypeError when attributes are accessed.
                    case_sens = getattr(self, 'flag_case_sensitive', True)

                    class _DynamicFlagMatch:
                        def __init__(self, value, case_sensitive):
                            self.id = None
                            self.is_regex = False
                            # Use challenge-level case sensitivity as best-effort
                            self.is_case_sensitive = case_sensitive
                            self.flag_value = value
                            self.points_override = None
                            self.unlocks_challenge_id = None
                            self.flag_label = None

                    return _DynamicFlagMatch(submitted_flag, case_sens)
        
        # Legacy support: check old flag column if no flags defined
        if not flags and self.flag:
            if self.flag_case_sensitive:
                if submitted_flag == self.flag:
                    return True
            else:
                if submitted_flag.lower() == self.flag.lower():
                    return True
        
        return None
    
    def is_solved_by_user(self, user_id):
        """Check if challenge is solved by user"""
        from models.submission import Solve
        return Solve.objects(challenge=self, user=user_id).first() is not None
    
    def is_solved_by_team(self, team_id):
        """Check if challenge is solved by team"""
        from models.submission import Solve
        return Solve.objects(challenge=self, team=team_id).first() is not None
    
    def is_unlocked_for_user(self, user_id, team_id=None):
        """Check if challenge is unlocked for user/team based on prerequisites and flags"""
        from models.branching import ChallengePrerequisite, ChallengeUnlock
        
        # If not hidden, it's always unlocked
        if not self.is_hidden:
            return True
            
        # If hidden and no unlock mode, it's hidden (unless admin, checked by caller)
        if self.unlock_mode == 'none':
            return False
        
        # Check prerequisite mode
        if self.unlock_mode == 'prerequisite':
            # Check if all prerequisites are solved
            from models.branching import ChallengePrerequisite
            prerequisites = ChallengePrerequisite.objects(challenge=self)
            if not prerequisites:
                return True  # No prerequisites defined, so unlocked
            
            for prereq in prerequisites:
                # Check if prerequisite is solved by user or team
                if team_id:
                    if not prereq.prerequisite_challenge.is_solved_by_team(team_id):
                        return False
                else:
                    if not prereq.prerequisite_challenge.is_solved_by_user(user_id):
                        return False
            
            return True  # All prerequisites met
        
        # Check flag unlock mode
        if self.unlock_mode == 'flag_unlock':
            # Check if challenge was unlocked by a flag
            from models.branching import ChallengeUnlock
            from mongoengine.queryset.visitor import Q
            query = ChallengeUnlock.objects(challenge=self)
            
            if team_id:
                # If in a team, check if unlocked by user OR by team
                query = query.filter(
                    (Q(user=user_id) | Q(team=team_id))
                )
            else:
                # If solo, ONLY check user_id (ignore team_id=None records from other solo users)
                query = query.filter(user=user_id)
                
            unlock = query.first()
            return unlock is not None
        
        return False
    
    def get_missing_prerequisites(self, user_id, team_id=None):
        """Get list of prerequisite challenges that are not yet solved"""
        from models.branching import ChallengePrerequisite
        
        if self.unlock_mode != 'prerequisite':
            return []
        
        prerequisites = ChallengePrerequisite.objects(challenge=self)
        missing = []
        
        for prereq in prerequisites:
            if team_id:
                if not prereq.prerequisite_challenge.is_solved_by_team(team_id):
                    missing.append(prereq.prerequisite_challenge)
            else:
                if not prereq.prerequisite_challenge.is_solved_by_user(user_id):
                    missing.append(prereq.prerequisite_challenge)
        
        return missing
    
    def to_dict(self, include_flag=False, include_solves=True):
        """Convert challenge to dictionary"""
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'act': self.act,
            'points': self.get_current_points(),
            'initial_points': self.initial_points,
            'minimum_points': self.minimum_points,
            'is_visible': self.is_visible,
            'is_dynamic': self.is_dynamic,
            'author': self.author,
            'difficulty': self.difficulty,
            'connection_info': self.connection_info,
            'files': self.files,
            'hints': self.hints,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # Docker fields
            'docker_enabled': self.docker_enabled,
            'docker_image': self.docker_image,
            'docker_connection_info': self.docker_connection_info,
            'docker_flag_path': self.docker_flag_path,
            'detect_regex_sharing': self.detect_regex_sharing,
            'requires_team': self.requires_team,
            'unlocks_act': self.unlocks_act
        }
        
        if include_solves:
            data['solves'] = self.get_solves_count()
            data['submissions'] = self.get_submissions_count()
        
        if include_flag:
            data['flag'] = self.flag
            data['flag_case_sensitive'] = self.flag_case_sensitive
        
        return data
    
    def __repr__(self):
        return f'<Challenge {self.name}>'
