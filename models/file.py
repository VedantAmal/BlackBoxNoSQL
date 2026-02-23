from models import db
from datetime import datetime

class ChallengeFile(db.Document):
    """Model for tracking challenge files"""
    meta = {'collection': 'challenge_files'}
    
    challenge = db.ReferenceField('Challenge', required=True)
    
    # File information
    original_filename = db.StringField(max_length=255, required=True)
    stored_filename = db.StringField(max_length=255, required=True)
    filepath = db.StringField(max_length=512, required=True)
    relative_path = db.StringField(max_length=512, required=True)
    
    # File metadata
    file_hash = db.StringField(max_length=64)
    file_size = db.IntField()
    mime_type = db.StringField(max_length=100)
    is_image = db.BooleanField(default=False)
    
    # Timestamps
    uploaded_at = db.DateTimeField(default=datetime.utcnow)
    uploaded_by = db.ReferenceField('User')
    
    def get_download_url(self):
        """Get the download URL for this file"""
        # Avoid using backslashes inside f-strings (which causes a SyntaxError)
        cleaned = self.relative_path.replace('\\', '/') if self.relative_path else ''
        return '/files/' + cleaned
    
    def format_size(self):
        """Format file size in human-readable format"""
        if not self.file_size:
            return "Unknown"
        
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"
    
    def to_dict(self):
        """Convert file to dictionary"""
        return {
            'id': str(self.id),
            'challenge_id': str(self.challenge.id) if self.challenge else None,
            'filename': self.original_filename,
            'original_filename': self.original_filename,
            'stored_filename': self.stored_filename,
            'size': self.format_size(),
            'url': self.get_download_url(),
            'download_url': self.get_download_url(),
            'is_image': self.is_image,
            'file_hash': self.file_hash,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None
        }
    
    def __repr__(self):
        return f'<ChallengeFile {self.original_filename}>'

# Alias for backward compatibility
File = ChallengeFile
