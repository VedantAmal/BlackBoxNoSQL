from flask_mongoengine import MongoEngine
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = MongoEngine()

# Import models here to avoid circular imports
# Note: In MongoEngine, we don't need to association table 'team_members'
# We can use ListField(ReferenceField(User)) in Team model or similar.

# Core models must be imported first to ensure registration
# Order matters! Team must be imported before User because User references Team
from models.team import Team
from models.user import User

# Manually register the circular delete rule for Team.captain
# This allows Team to be defined before User is fully registered
Team.register_delete_rule(User, 'captain', db.NULLIFY)

from models.challenge import Challenge
from models.submission import Submission, Solve
from models.file import File, ChallengeFile
from models.hint import Hint, HintUnlock

# Dependent models
from models.branching import ChallengeFlag, ChallengePrerequisite, ChallengeUnlock
from models.notification import Notification
from models.notification_read import NotificationRead
from models.settings import Settings, DockerSettings
from models.container import ContainerInstance, ContainerEvent
from models.flag_abuse import FlagAbuseAttempt
from models.act_unlock import ActUnlock

