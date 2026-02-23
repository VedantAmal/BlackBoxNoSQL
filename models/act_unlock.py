from datetime import datetime
from models import db

class ActUnlock(db.Document):
    """Track which ACTs are unlocked for users/teams"""
    meta = {'collection': 'act_unlocks'}
    
    act = db.StringField(max_length=20, required=True)
    
    # Either user_id or team_id will be set
    user = db.ReferenceField('User', reverse_delete_rule=db.CASCADE)
    team = db.ReferenceField('Team', reverse_delete_rule=db.CASCADE)
    
    # Which challenge unlocked this act
    unlocked_by_challenge = db.ReferenceField('Challenge', reverse_delete_rule=db.NULLIFY)
    
    unlocked_at = db.DateTimeField(default=datetime.utcnow, required=True)
    
    @staticmethod
    def is_act_unlocked(act, user_id=None, team_id=None):
        """Check if an ACT is unlocked for a user or team"""
        # ACT I is always unlocked
        if act == 'ACT I':
            return True
        # Admin bypass: if current user is admin, treat as unlocked
        try:
            from flask_login import current_user
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and getattr(current_user, 'is_admin', False):
                return True
        except Exception:
            # If no request context / current_user not available, continue to DB check
            pass

        if team_id:
            # If in a team, check if unlocked by user OR by team
            # MongoEngine Q objects for OR queries
            from mongoengine.queryset.visitor import Q
            return ActUnlock.objects(
                Q(act=act) & (Q(user=user_id) | Q(team=team_id))
            ).first() is not None
        elif user_id:
            # If solo, ONLY check user_id (ignore team_id=None records from other solo users)
            return ActUnlock.objects(act=act, user=user_id).first() is not None
        
        return False

        return False
    
    @staticmethod
    def unlock_act(act, user_id=None, team_id=None, challenge_id=None):
        """Unlock an ACT for a user or team"""
        from models import db
        # Admin bypass: do not create records for admins (they have all acts by default)
        try:
            from flask_login import current_user
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and getattr(current_user, 'is_admin', False):
                return False
        except Exception:
            # No request context; fall back to normal behavior
            pass

        # Check if already unlocked
        if ActUnlock.is_act_unlocked(act, user_id=user_id, team_id=team_id):
            return False
        
        # Create unlock record
        unlock = ActUnlock(
            act=act,
            user=user_id,
            team=team_id,
            unlocked_by_challenge=challenge_id
        )
        unlock.save()
        return True
    
    @staticmethod
    def get_unlocked_acts(user_id=None, team_id=None):
        """Get list of unlocked ACTs for a user or team"""
        # ACT I is always unlocked
        unlocked = ['ACT I']

        # Admin bypass: return all acts for admins
        try:
            from flask_login import current_user
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated and getattr(current_user, 'is_admin', False):
                return ['ACT I', 'ACT II', 'ACT III', 'ACT IV', 'ACT V']
        except Exception:
            pass

        from mongoengine.queryset.visitor import Q

        if team_id:
            acts = ActUnlock.objects(
                (Q(user=user_id) | Q(team=team_id))
            ).order_by('unlocked_at')
        elif user_id:
            acts = ActUnlock.objects(
                user=user_id
            ).order_by('unlocked_at')
        else:
            return unlocked

        for act_unlock in acts:
            if act_unlock.act not in unlocked:
                unlocked.append(act_unlock.act)

        return unlocked
    
    def __repr__(self):
        return f'<ActUnlock {self.act} for {"team_" + str(self.team_id) if self.team_id else "user_" + str(self.user_id)}>'
