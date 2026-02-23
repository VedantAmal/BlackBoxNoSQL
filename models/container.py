from datetime import datetime
from models import db

class ContainerInstance(db.Document):
    """Model for tracking active container instances"""
    meta = {'collection': 'container_instances'}
    
    challenge = db.ReferenceField('Challenge', required=True)
    user = db.ReferenceField('User', required=True)
    team = db.ReferenceField('Team')
    
    # Docker container details
    container_id = db.StringField(max_length=128, required=True, unique=True)
    container_name = db.StringField(max_length=256, required=True)
    docker_image = db.StringField(max_length=256, required=True)
    
    # Network details
    port = db.IntField(required=True)
    host_ip = db.StringField(max_length=256)  # Docker host IP
    host_port = db.IntField()  # Mapped host port
    ip_address = db.StringField(max_length=45)  # Container IP address
    docker_info = db.DictField()  # Additional Docker metadata
    
    # State tracking
    status = db.StringField(max_length=20, default='starting')  # starting, running, stopping, stopped, error
    session_id = db.StringField(max_length=64, required=True, unique=True)
    
    # Timestamps
    created_at = db.DateTimeField(default=datetime.utcnow, required=True)
    started_at = db.DateTimeField()
    expires_at = db.DateTimeField(required=True)
    last_revert_time = db.DateTimeField()
    
    # Error tracking
    error_message = db.StringField()
    
    # Dynamic flag storage (unique per-team, per-challenge, per-instance)
    dynamic_flag = db.StringField(max_length=512)
    
    def __repr__(self):
        return f'<ContainerInstance {self.container_name} (user={self.user.id}, challenge={self.challenge.id})>'
    
    def to_dict(self):
        """Convert instance to dictionary"""
        # Build connection info if we have challenge data
        connection_info = None
        if self.challenge and self.challenge.docker_connection_info:
            connection_info = self.challenge.docker_connection_info.replace(
                '{host}', self.host_ip or 'localhost'
            ).replace(
                '{port}', str(self.host_port) if self.host_port else ''
            )
        
        # Calculate expires_at in milliseconds since epoch for JS to use (avoids timezone confusion)
        expires_at_ms = None
        if self.expires_at:
            expires_at_ms = int(self.expires_at.timestamp() * 1000)
        
        return {
            'id': str(self.id),
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'user_id': str(self.user.id) if self.user else None,
            'team_id': str(self.team.id) if self.team else None,
            'container_id': self.container_id,
            'container_name': self.container_name,
            'docker_image': self.docker_image,
            'port': self.port,
            'host_ip': self.host_ip,
            'host_port': self.host_port,
            'ip_address': self.ip_address,
            'status': self.status,
            'session_id': self.session_id,
            'connection_info': connection_info,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'expires_at_ms': expires_at_ms,  # Milliseconds since epoch for JS countdown
            'last_revert_time': self.last_revert_time.isoformat() if self.last_revert_time else None,
            'error_message': self.error_message
        }
    
    def is_expired(self):
        """Check if container has expired"""
        return datetime.utcnow() > self.expires_at
    
    def is_active(self):
        """Check if container is in an active state"""
        return self.status in ['starting', 'running']
    
    def get_remaining_time(self):
        """Get remaining time in human-readable format"""
        if not self.expires_at:
            return 'N/A'
        
        now = datetime.utcnow()
        if now >= self.expires_at:
            return 'Expired'
        
        delta = self.expires_at - now
        
        # Calculate hours, minutes, seconds
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        # Format based on time remaining
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def get_expected_flag(self):
        """Get the expected dynamic flag for this container from cache or DB"""
        from services.cache import cache_service
        
        # First try DB column
        if self.dynamic_flag:
            return self.dynamic_flag
        
        # Fallback to cache (legacy)
        cache_key = f"dynamic_flag:{self.session_id}"
        cached_flag = cache_service.get(cache_key)
        if cached_flag:
            return cached_flag
        
        # Try mapping cache (team-based)
        if self.team_id:
            team_part = f'team_{self.team_id}'
        else:
            team_part = f'user_{self.id}'
        
        mapping_key = f"dynamic_flag_mapping:{self.challenge_id}:{team_part}"
        mapped_flag = cache_service.get(mapping_key)
        return mapped_flag
    
    def verify_flag(self, submitted_flag):
        """Verify if submitted flag matches this container's expected flag"""
        expected = self.get_expected_flag()
        if not expected:
            return {'valid': False, 'reason': 'No dynamic flag generated for this container'}
        
        # Check case-sensitive match
        if submitted_flag == expected:
            return {'valid': True, 'expected': expected}
        
        # Check case-insensitive if challenge allows
        if self.challenge and not getattr(self.challenge, 'flag_case_sensitive', True):
            if submitted_flag.lower() == expected.lower():
                return {'valid': True, 'expected': expected, 'note': 'Case-insensitive match'}
        
        return {'valid': False, 'expected': expected, 'submitted': submitted_flag}


class ContainerEvent(db.Document):
    """Model for logging container lifecycle events"""
    meta = {'collection': 'container_events'}
    
    container_instance = db.ReferenceField('ContainerInstance', reverse_delete_rule=db.NULLIFY)
    challenge = db.ReferenceField('Challenge', required=True)
    user = db.ReferenceField('User', required=True)
    
    # Event details
    event_type = db.StringField(max_length=50, required=True)  # start, stop, revert, expire, error
    status = db.StringField(max_length=20, required=True)  # success, failure, pending
    message = db.StringField()
    
    # Metadata
    ip_address = db.StringField(max_length=45)
    container_id = db.StringField(max_length=128)
    
    # Timestamp
    timestamp = db.DateTimeField(default=datetime.utcnow, required=True)
    
    def __repr__(self):
        return f'<ContainerEvent {self.event_type} (user={self.user_id}, challenge={self.challenge_id})>'
    
    def to_dict(self):
        """Convert event to dictionary"""
        return {
            'id': str(self.id),
            'container_instance_id': str(self.container_instance.id) if self.container_instance else None,
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'user_id': str(self.user.id) if self.user else None,
            'event_type': self.event_type,
            'status': self.status,
            'message': self.message,
            'ip_address': self.ip_address,
            'container_id': self.container_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
