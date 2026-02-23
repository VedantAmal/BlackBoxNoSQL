# Migration to MongoDB

This codebase has been migrated from MySQL (SQLAlchemy) to MongoDB (MongoEngine).

## Changes Made

1.  **Dependencies**:
    *   Removed `Flask-SQLAlchemy`, `PyMySQL`, `Flask-Migrate`.
    *   Added `flask-mongoengine`, `mongoengine`.

2.  **Configuration**:
    *   Updated `config.py` to use `MONGODB_SETTINGS`.
    *   Removed SQL connection pool settings.

3.  **Database Initialization**:
    *   Updated `models/__init__.py` to initialize `MongoEngine`.
    *   Updated `init_db.py` to remove SQL table creation logic.

4.  **Models**:
    *   Converted the following models to `MongoEngine.Document`:
        *   `User` (`models/user.py`)
        *   `Team` (`models/team.py`)
        *   `Challenge` (`models/challenge.py`)
        *   `Submission`, `Solve` (`models/submission.py`)
        *   `Hint`, `HintUnlock` (`models/hint.py`)
        *   `Settings`, `DockerSettings` (`models/settings.py`)
    *   Changed `id` fields to use MongoDB's default `ObjectId`.
    *   Changed relationships to use `ReferenceField` and `ListField`.

5.  **Application Logic**:
    *   Updated `app.py` to use `User.objects(...)` instead of `User.query.get(...)`.
    *   Updated `app.py` to use `ChallengeFile.objects(...)`.
    *   Updated `app.py` health check to ping MongoDB.

## Remaining Work

1.  **Migrate Remaining Models**:
    *   `models/act_unlock.py`
    *   `models/branching.py`
    *   `models/container.py`
    *   `models/file.py`
    *   `models/flag_abuse.py`
    *   `models/notification.py`
    *   `models/notification_read.py`

2.  **Update Routes and Services**:
    *   The code in `routes/` and `services/` likely contains many SQL-specific queries (`.query.filter_by`, `db.session.add`, `db.session.commit`).
    *   These need to be updated to use MongoEngine syntax (`.objects(...)`, `.save()`).

3.  **Scripts**:
    *   `scripts/` folder contains maintenance scripts that need to be updated.

4.  **Testing**:
    *   Thorough testing is required to ensure all features work with the new database.
