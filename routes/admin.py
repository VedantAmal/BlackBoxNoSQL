from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
from models.user import User
from models.team import Team
from models.challenge import Challenge
from models.submission import Submission, Solve
from models.file import ChallengeFile
from models.hint import Hint, HintUnlock
from models.settings import Settings
from services.cache import cache_service
from services.file_storage import file_storage
import json
from models.notification import Notification
from services.websocket import WebSocketService

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    """Admin dashboard"""
    # Get statistics
    stats = {
        'users': User.objects.count(),
        'teams': Team.objects.count(),
        'challenges': Challenge.objects.count(),
        'submissions': Submission.objects.count(),
        'solves': Solve.objects(challenge__ne=None).count()
    }
    
    # Recent activity
    recent_solves = Solve.objects.order_by('-solved_at').limit(10)
    
    return render_template('admin/dashboard.html', stats=stats, recent_solves=recent_solves)


# Challenge Management
@admin_bp.route('/challenges')
@login_required
@admin_required
def manage_challenges():
    """Manage challenges page"""
    # Support sorting by query parameter e.g. ?sort=act&order=asc
    sort = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')

    query = Challenge.objects
    if sort == 'act':
        if order == 'desc':
            query = query.order_by('-act', 'name')
        else:
            query = query.order_by('act', 'name')
    else:
        # Default: sort by name
        if order == 'desc':
            query = query.order_by('-name')
        else:
            query = query.order_by('name')

    challenges = query
    return render_template('admin/challenges.html', challenges=challenges, current_sort=sort, current_order=order)


@admin_bp.route('/challenges/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_challenge():
    """Create a new challenge"""
    # Check if ACT system is enabled
    act_system_enabled = Settings.get('act_system_enabled', default=False, type='bool')
    
    if request.method == 'POST':
        from models.branching import ChallengeFlag
        
        data = request.form
        
        # Only set ACT fields if ACT system is enabled
        act_value = data.get('act', 'ACT I') if act_system_enabled else None
        unlocks_act_value = (data.get('unlocks_act') if data.get('unlocks_act') else None) if act_system_enabled else None
        
        challenge = Challenge(
            name=data.get('name'),
            description=data.get('description'),
            category=data.get('category'),
            act=act_value,
            flag=data.get('flag'),
            flag_case_sensitive=data.get('flag_case_sensitive') == 'true',
            connection_info=data.get('connection_info'),
            initial_points=int(data.get('initial_points', 500)),
            minimum_points=int(data.get('minimum_points', 50)),
            decay_solves=int(data.get('decay_solves', 30)),
            max_attempts=int(data.get('max_attempts', 0)),
            is_visible=data.get('is_visible') == 'true',
            is_dynamic=data.get('is_dynamic') == 'true',
            requires_team=data.get('requires_team') == 'true',
            author=data.get('author'),
            difficulty=data.get('difficulty'),
            unlocks_act=unlocks_act_value,
            # Docker fields
            docker_enabled=data.get('docker_enabled') == 'true',
            docker_image=data.get('docker_image') if data.get('docker_enabled') == 'true' else None,
            docker_connection_info=data.get('docker_connection_info') if data.get('docker_enabled') == 'true' else None,
            docker_flag_path=data.get('docker_flag_path') if data.get('docker_enabled') == 'true' else None,
            detect_regex_sharing=data.get('detect_regex_sharing') == 'true'
        )
        
        challenge.save()
        
        # Create primary flag entry in challenge_flags table
        primary_flag = ChallengeFlag(
            challenge=challenge,
            flag_value=data.get('flag'),
            flag_label='Primary Flag',
            is_case_sensitive=data.get('flag_case_sensitive') == 'true',
            is_regex=data.get('is_regex') == 'true'
        )
        primary_flag.save()
        
        # Handle additional flags
        additional_flags = request.form.getlist('additional_flags[]')
        flag_labels = request.form.getlist('flag_labels[]')
        flag_points = request.form.getlist('flag_points[]')
        flag_cases = request.form.getlist('flag_case[]')
        flag_is_regex = request.form.getlist('flag_is_regex[]')
        
        for i in range(len(additional_flags)):
            if additional_flags[i].strip():
                points_override = None
                if i < len(flag_points) and flag_points[i].strip():
                    try:
                        points_override = int(flag_points[i])
                    except ValueError:
                        pass
                
                additional_flag = ChallengeFlag(
                    challenge=challenge,
                    flag_value=additional_flags[i].strip(),
                    flag_label=flag_labels[i].strip() if i < len(flag_labels) and flag_labels[i].strip() else None,
                    points_override=points_override,
                    is_case_sensitive=flag_cases[i] == 'true' if i < len(flag_cases) else True,
                    is_regex=(i < len(flag_is_regex) and flag_is_regex[i] == 'true')
                )
                additional_flag.save()
        
        # Handle hints
        hint_contents = request.form.getlist('hint_content[]')
        hint_costs = request.form.getlist('hint_cost[]')
        hint_orders = request.form.getlist('hint_order[]')
        hint_requires = request.form.getlist('hint_requires[]')
        
        # First pass: Create hints without prerequisites
        created_hints = {}
        for i in range(len(hint_contents)):
            if hint_contents[i].strip():
                order = int(hint_orders[i]) if i < len(hint_orders) else (i + 1)
                hint = Hint(
                    challenge=challenge,
                    content=hint_contents[i],
                    cost=int(hint_costs[i]) if i < len(hint_costs) else 10,
                    order=order
                )
                hint.save()
                created_hints[order] = hint
        
        # Second pass: Set prerequisites based on order
        for i in range(len(hint_contents)):
            if hint_contents[i].strip():
                order = int(hint_orders[i]) if i < len(hint_orders) else (i + 1)
                requires_order = hint_requires[i] if i < len(hint_requires) and hint_requires[i] else None
                
                if requires_order and requires_order.strip():
                    requires_order = int(requires_order)
                    if requires_order in created_hints:
                        created_hints[order].requires_hint = created_hints[requires_order]
                        created_hints[order].save()
        
        # Handle file uploads
        uploaded_files = []
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and file.filename:
                    try:
                        file_info = file_storage.save_challenge_file(file, challenge.id)
                        if file_info:
                            # Create ChallengeFile record
                            challenge_file = ChallengeFile(
                                challenge=challenge,
                                original_filename=file_info['original_filename'],
                                stored_filename=file_info['stored_filename'],
                                filepath=file_info['filepath'],
                                relative_path=file_info['relative_path'],
                                file_hash=file_info['hash'],
                                file_size=file_info['size'],
                                uploaded_by=current_user
                            )
                            challenge_file.save()
                            uploaded_files.append(file_info)
                    except Exception as e:
                        flash(f'Error uploading file {file.filename}: {str(e)}', 'warning')
        
        # Store file URLs in challenge (for backward compatibility)
        if uploaded_files:
            file_urls = [f['url'] for f in uploaded_files]
            challenge.files = file_urls
        
        # Handle image uploads
        uploaded_images = []
        if 'images' in request.files:
            images = request.files.getlist('images')
            for image in images:
                if image and image.filename:
                    try:
                        image_info = file_storage.save_challenge_file(image, challenge.id)
                        if image_info:
                            # Create ChallengeFile record for image
                            challenge_image = ChallengeFile(
                                challenge=challenge,
                                original_filename=image_info['original_filename'],
                                stored_filename=image_info['stored_filename'],
                                filepath=image_info['filepath'],
                                relative_path=image_info['relative_path'],
                                file_hash=image_info['hash'],
                                file_size=image_info['size'],
                                uploaded_by=current_user,
                                is_image=True  # Mark as image
                            )
                            challenge_image.save()
                            uploaded_images.append(image_info)
                    except Exception as e:
                        flash(f'Error uploading image {image.filename}: {str(e)}', 'warning')
        
        # Store image URLs in challenge
        if uploaded_images:
            image_urls = [{'url': img['url'], 'original_filename': img['original_filename']} for img in uploaded_images]
            challenge.images = image_urls
        
        challenge.save()
        
        cache_service.invalidate_all_challenges()
        
        flash(f'Challenge "{challenge.name}" created successfully!', 'success')
        
        return redirect(url_for('admin.manage_challenges'))
    
    return render_template('admin/create_challenge.html', act_system_enabled=act_system_enabled)

@admin_bp.route('/challenges/<string:challenge_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_challenge(challenge_id):
    """Edit a challenge"""
    challenge = Challenge.objects(id=challenge_id).first_or_404()
    
    # Check if ACT system is enabled
    act_system_enabled = Settings.get('act_system_enabled', default=False, type='bool')
    
    if request.method == 'POST':
        from models.branching import ChallengeFlag
        data = request.form
        
        challenge.name = data.get('name')
        challenge.description = data.get('description')
        challenge.category = data.get('category')
        # Only set ACT fields if ACT system is enabled
        challenge.act = data.get('act', 'ACT I') if act_system_enabled else None
        challenge.flag = data.get('flag')
        challenge.flag_case_sensitive = data.get('flag_case_sensitive') == 'true'
        challenge.connection_info = data.get('connection_info')
        challenge.initial_points = int(data.get('initial_points', 500))
        challenge.minimum_points = int(data.get('minimum_points', 50))
        challenge.decay_solves = int(data.get('decay_solves', 30))
        challenge.max_attempts = int(data.get('max_attempts', 0))
        challenge.is_visible = data.get('is_visible') == 'true'
        challenge.is_dynamic = data.get('is_dynamic') == 'true'
        challenge.requires_team = data.get('requires_team') == 'true'
        challenge.author = data.get('author')
        challenge.difficulty = data.get('difficulty')
        challenge.unlocks_act = (data.get('unlocks_act') if data.get('unlocks_act') else None) if act_system_enabled else None
        
        # Handle Docker container settings
        challenge.docker_enabled = data.get('docker_enabled') == 'true'
        if challenge.docker_enabled:
            docker_image_value = data.get('docker_image')
            if docker_image_value == 'custom' or not docker_image_value:
                # Use manual input
                challenge.docker_image = data.get('docker_image_manual')
            else:
                # Use selected image
                challenge.docker_image = docker_image_value
            challenge.docker_connection_info = data.get('docker_connection_info', 'http://{host}:{port}')
            # Optional: path inside the container to write the dynamic flag (e.g. /flag.txt)
            challenge.docker_flag_path = data.get('docker_flag_path')
        else:
            challenge.docker_image = None
            challenge.docker_connection_info = None

        # Regex sharing detection toggle
        challenge.detect_regex_sharing = data.get('detect_regex_sharing') == 'true'
        
        # Update primary flag in challenge_flags table
        primary_flag = ChallengeFlag.objects(
            challenge=challenge,
            flag_label='Primary Flag'
        ).first()
        
        if primary_flag:
            primary_flag.flag_value = data.get('flag')
            primary_flag.is_case_sensitive = data.get('flag_case_sensitive') == 'true'
            primary_flag.is_regex = data.get('is_regex') == 'true'
            primary_flag.save()
        else:
            # Create primary flag if it doesn't exist
            primary_flag = ChallengeFlag(
                challenge=challenge,
                flag_value=data.get('flag'),
                flag_label='Primary Flag',
                is_case_sensitive=data.get('flag_case_sensitive') == 'true',
                is_regex=data.get('is_regex') == 'true'
            )
            primary_flag.save()
        
        # Handle existing hints updates
        existing_hints = Hint.objects(challenge=challenge)
        for hint in existing_hints:
            content_key = f'existing_hint_content_{hint.id}'
            cost_key = f'existing_hint_cost_{hint.id}'
            order_key = f'existing_hint_order_{hint.id}'
            requires_key = f'existing_hint_requires_{hint.id}'
            
            if content_key in data:
                hint.content = data[content_key]
                hint.cost = int(data[cost_key])
                hint.order = int(data[order_key])
                
                # Handle prerequisite
                requires_id = data.get(requires_key)
                if requires_id and requires_id.strip():
                    hint.requires_hint = Hint.objects(id=requires_id).first()
                else:
                    hint.requires_hint = None
                hint.save()
        
        # Handle new hints
        hint_contents = request.form.getlist('hint_content[]')
        hint_costs = request.form.getlist('hint_cost[]')
        hint_orders = request.form.getlist('hint_order[]')
        hint_requires = request.form.getlist('hint_requires[]')
        
        # First pass: Create hints without prerequisites
        created_hints = []
        for i in range(len(hint_contents)):
            if hint_contents[i].strip():
                hint = Hint(
                    challenge=challenge,
                    content=hint_contents[i],
                    cost=int(hint_costs[i]) if i < len(hint_costs) else 10,
                    order=int(hint_orders[i]) if i < len(hint_orders) else (i + 1)
                )
                hint.save()
                created_hints.append((hint, i))
        
        # Second pass: Set prerequisites for new hints
        for hint, i in created_hints:
            requires_id = hint_requires[i] if i < len(hint_requires) and hint_requires[i] else None
            if requires_id and requires_id.strip():
                hint.requires_hint = Hint.objects(id=requires_id).first()
                hint.save()
        
        # Handle new file uploads
        if 'files' in request.files:
            files = request.files.getlist('files')
            uploaded_files = []
            
            for file in files:
                if file and file.filename:
                    try:
                        file_info = file_storage.save_challenge_file(file, challenge.id)
                        if file_info:
                            # Create ChallengeFile record
                            challenge_file = ChallengeFile(
                                challenge=challenge,
                                original_filename=file_info['original_filename'],
                                stored_filename=file_info['stored_filename'],
                                filepath=file_info['filepath'],
                                relative_path=file_info['relative_path'],
                                file_hash=file_info['hash'],
                                file_size=file_info['size'],
                                uploaded_by=current_user
                            )
                            challenge_file.save()
                            uploaded_files.append(file_info)
                    except Exception as e:
                        flash(f'Error uploading file {file.filename}: {str(e)}', 'warning')
            
            # Update file URLs if new files were uploaded
            if uploaded_files:
                existing_urls = challenge.files if challenge.files else []
                new_urls = [f['url'] for f in uploaded_files]
                all_urls = existing_urls + new_urls
                challenge.files = all_urls
        
        # Handle new image uploads
        if 'images' in request.files:
            images = request.files.getlist('images')
            uploaded_images = []
            
            for image in images:
                if image and image.filename:
                    try:
                        image_info = file_storage.save_challenge_file(image, challenge.id)
                        if image_info:
                            # Create ChallengeFile record for image
                            challenge_image = ChallengeFile(
                                challenge=challenge,
                                original_filename=image_info['original_filename'],
                                stored_filename=image_info['stored_filename'],
                                filepath=image_info['filepath'],
                                relative_path=image_info['relative_path'],
                                file_hash=image_info['hash'],
                                file_size=image_info['size'],
                                uploaded_by=current_user,
                                is_image=True
                            )
                            challenge_image.save()
                            uploaded_images.append(image_info)
                    except Exception as e:
                        flash(f'Error uploading image {image.filename}: {str(e)}', 'warning')
            
            # Update image URLs if new images were uploaded
            if uploaded_images:
                existing_imgs = challenge.images if challenge.images else []
                new_imgs = [{'url': img['url'], 'original_filename': img['original_filename']} for img in uploaded_images]
                all_imgs = existing_imgs + new_imgs
                challenge.images = all_imgs
        
        challenge.save()
        
        cache_service.invalidate_challenge(challenge_id)
        cache_service.invalidate_all_challenges()
        
        flash(f'Challenge "{challenge.name}" updated successfully!', 'success')
        return redirect(url_for('admin.manage_challenges'))
    
    # Get existing files and hints
    existing_files = ChallengeFile.objects(challenge=challenge, is_image=False)
    existing_images = ChallengeFile.objects(challenge=challenge, is_image=True)
    existing_hints = Hint.objects(challenge=challenge).order_by('order')
    
    # Get primary flag to check is_regex status
    from models.branching import ChallengeFlag
    primary_flag = ChallengeFlag.objects(
        challenge=challenge,
        flag_label='Primary Flag'
    ).first()
    
    return render_template('admin/edit_challenge.html', 
                          challenge=challenge, 
                          existing_files=existing_files,
                          existing_images=existing_images,
                          existing_hints=existing_hints,
                          primary_flag=primary_flag,
                          act_system_enabled=act_system_enabled)


@admin_bp.route('/challenges/<string:challenge_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_challenge(challenge_id):
    """Delete a challenge"""
    challenge = Challenge.objects(id=challenge_id).first_or_404()
    
    # Delete associated data in correct order (respecting foreign key constraints)
    from models.branching import ChallengeFlag, ChallengePrerequisite, ChallengeUnlock
    from models.hint import HintUnlock
    
    # Step 1: Delete solves (references challenge_flags.id)
    Solve.objects(challenge=challenge).delete()
    
    # Step 2: Delete submissions
    Submission.objects(challenge=challenge).delete()
    
    # Step 3: Delete hint unlocks (references hints.id)
    # Hint unlocks are usually linked to hints, so we delete hints and let cascade handle it if possible,
    # or delete manually. Assuming HintUnlock references Hint.
    # Hint.objects(challenge=challenge).delete() will delete hints.
    # We should delete HintUnlocks first if they reference hints.
    # But wait, HintUnlock references Hint.
    # Let's find all hints for this challenge
    hints = Hint.objects(challenge=challenge)
    for hint in hints:
        HintUnlock.objects(hint=hint).delete()
    hints.delete()
    
    # Step 4: Delete unlock records
    ChallengeUnlock.objects(challenge=challenge).delete()
    
    # Step 5: Delete prerequisites where this challenge is required or is the dependent
    from mongoengine.queryset.visitor import Q
    ChallengePrerequisite.objects(
        Q(challenge=challenge) | Q(prerequisite_challenge=challenge)
    ).delete()
    
    # Step 6: Delete flags that unlock this challenge (set to NULL)
    ChallengeFlag.objects(unlocks_challenge=challenge).update(set__unlocks_challenge=None)
    
    # Step 7: Delete all flags for this challenge
    ChallengeFlag.objects(challenge=challenge).delete()

    # Step 7a: Delete container instances and related events for this challenge
    try:
        from models.container import ContainerInstance, ContainerEvent
        from services.container_manager import container_orchestrator
        import docker

        # Stop and remove any real docker containers, then remove DB records
        instances = ContainerInstance.objects(challenge=challenge)
        for inst in instances:
            try:
                if container_orchestrator and container_orchestrator.docker_client:
                    try:
                        docker_container = container_orchestrator.docker_client.containers.get(inst.container_id)
                        docker_container.stop(timeout=10)
                        docker_container.remove()
                    except docker.errors.NotFound:
                        pass
                    except Exception as e:
                        current_app.logger.warning(f"Failed to stop/remove container {inst.container_id}: {e}")
            except Exception:
                # If the orchestrator itself isn't available, continue to delete DB records
                pass

            # Delete any container events referencing this instance
            ContainerEvent.objects(container_instance=inst).delete()
            # Delete the instance record
            inst.delete()

        # Also remove any container events that reference the challenge directly
        ContainerEvent.objects(challenge=challenge).delete()
    except Exception as e:
        current_app.logger.warning(f"Error cleaning up container records for challenge {challenge_id}: {e}")

    # Step 7b: Remove any flag abuse records referencing this challenge
    try:
        from models.flag_abuse import FlagAbuseAttempt
        FlagAbuseAttempt.objects(challenge=challenge).delete()
    except Exception:
        pass
    
    # Step 8: Delete associated files from filesystem
    file_storage.delete_challenge_files(challenge.id)
    
    # Step 9: Delete file records from database
    ChallengeFile.objects(challenge=challenge).delete()
    
    # Step 10: Finally delete the challenge itself
    challenge.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    cache_service.invalidate_all_challenges()
    cache_service.invalidate_scoreboard()
    
    return jsonify({'success': True, 'message': 'Challenge deleted'})


@admin_bp.route('/challenges/<string:challenge_id>/toggle-enabled', methods=['POST'])
@login_required
@admin_required
def toggle_challenge_enabled(challenge_id):
    """Toggle challenge enabled status"""
    challenge = Challenge.objects(id=challenge_id).first_or_404()
    
    challenge.is_enabled = not challenge.is_enabled
    challenge.save()
    
    cache_service.invalidate_challenge(challenge_id)
    cache_service.invalidate_all_challenges()
    
    status = "enabled" if challenge.is_enabled else "disabled"
    return jsonify({
        'success': True,
        'is_enabled': challenge.is_enabled,
        'message': f'Challenge {challenge.name} {status}'
    })


@admin_bp.route('/challenges/files/<string:file_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_challenge_file(file_id):
    """Delete a challenge file"""
    challenge_file = ChallengeFile.objects(id=file_id).first_or_404()
    challenge_id = challenge_file.challenge.id
    
    # Delete physical file
    file_storage.delete_file(challenge_file.filepath)
    
    # Delete database record
    challenge_file.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'File deleted'})


@admin_bp.route('/challenges/images/<string:image_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_challenge_image(image_id):
    """Delete a challenge image"""
    challenge_image = ChallengeFile.objects(id=image_id).first_or_404()
    challenge_id = challenge_image.challenge.id
    
    # Delete physical file
    file_storage.delete_file(challenge_image.filepath)
    
    # Delete database record
    challenge_image.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'Image deleted'})


# User Management
@admin_bp.route('/users')
@login_required
@admin_required
def manage_users():
    """Manage users page"""
    users = User.objects
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/<string:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    """Toggle admin status for a user"""
    user = User.objects(id=user_id).first_or_404()
    
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot modify your own admin status'}), 400
    
    user.is_admin = not user.is_admin
    user.save()
    
    return jsonify({
        'success': True,
        'is_admin': user.is_admin,
        'message': f'User {user.username} admin status updated'
    })


@admin_bp.route('/users/<string:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_active(user_id):
    """Toggle active status for a user"""
    user = User.objects(id=user_id).first_or_404()
    
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot deactivate yourself'}), 400
    
    user.is_active = not user.is_active
    user.save()
    
    return jsonify({
        'success': True,
        'is_active': user.is_active,
        'message': f'User {user.username} active status updated'
    })


# Team Management
@admin_bp.route('/teams')
@login_required
@admin_required
def manage_teams():
    """Manage teams page"""
    teams = Team.objects
    return render_template('admin/teams.html', teams=teams)


@admin_bp.route('/teams/<string:team_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_team(team_id):
    """Delete a team"""
    team = Team.objects(id=team_id).first_or_404()
    
    # Remove team from all members
    members = User.objects(team=team)
    for member in members:
        member.team = None
        member.is_team_captain = False
        member.save()
    
    team.delete()
    
    cache_service.invalidate_team(team_id)
    cache_service.invalidate_scoreboard()
    
    return jsonify({'success': True, 'message': 'Team deleted'})


# Points Management
@admin_bp.route('/users/<string:user_id>/adjust-points', methods=['POST'])
@login_required
@admin_required
def adjust_user_points(user_id):
    """Manually adjust user points by creating a solve adjustment"""
    from models.submission import Solve
    from models.challenge import Challenge
    
    user = User.objects(id=user_id).first_or_404()
    data = request.get_json()
    
    points_delta = int(data.get('points', 0))
    reason = data.get('reason', 'Manual adjustment by admin')
    
    if points_delta == 0:
        return jsonify({'success': False, 'message': 'Points delta cannot be zero'}), 400
    
    # Create a "virtual" solve record for tracking score adjustments
    # We'll create a challenge with ID 0 that represents manual adjustments
    adjustment = Solve(
        user=user,
        team=user.team,
        challenge=None,  # None indicates manual adjustment
        points_earned=points_delta,
        solved_at=datetime.utcnow()
    )
    
    adjustment.save()
    
    cache_service.invalidate_scoreboard()
    if user.team:
        cache_service.invalidate_team(user.team.id)
    cache_service.invalidate_user(user_id)
    
    return jsonify({
        'success': True,
        'new_score': user.get_score(),
        'message': f'Adjusted {user.username} points by {points_delta:+d}. Reason: {reason}'
    })


@admin_bp.route('/teams/<string:team_id>/adjust-points', methods=['POST'])
@login_required
@admin_required
def adjust_team_points(team_id):
    """Manually adjust team points by creating a solve adjustment"""
    from models.submission import Solve
    
    team = Team.objects(id=team_id).first_or_404()
    data = request.get_json()
    
    points_delta = int(data.get('points', 0))
    reason = data.get('reason', 'Manual adjustment by admin')
    
    if points_delta == 0:
        return jsonify({'success': False, 'message': 'Points delta cannot be zero'}), 400
    
    # Create adjustment solve for team
    adjustment = Solve(
        user=None,
        team=team,
        challenge=None,
        points_earned=points_delta,
        solved_at=datetime.utcnow()
    )
    
    adjustment.save()
    
    cache_service.invalidate_scoreboard()
    cache_service.invalidate_team(team_id)
    
    return jsonify({
        'success': True,
        'new_score': team.get_score(),
        'message': f'Adjusted {team.name} points by {points_delta:+d}. Reason: {reason}'
    })


@admin_bp.route('/users/<string:user_id>/solves', methods=['GET'])
@login_required
@admin_required
def get_user_solves(user_id):
    """Get solve history for a user including manual adjustments"""
    from models.submission import Solve
    from models.challenge import Challenge
    
    user = User.objects(id=user_id).first_or_404()
    
    solves = Solve.objects(user=user).order_by('-solved_at')
    
    solve_list = []
    for solve in solves:
        challenge = solve.challenge
        solve_list.append({
            'challenge_name': challenge.name if challenge else None,
            'points': solve.points_earned,
            'solved_at': solve.solved_at.isoformat(),
            'is_adjustment': challenge is None,
            'reason': None  # Could add reason field to Solve model
        })
    
    return jsonify({
        'success': True,
        'solves': solve_list
    })


@admin_bp.route('/users/<string:user_id>/activity')
@login_required
@admin_required
def user_activity(user_id):
    """View detailed user activity with pagination"""
    from models.submission import Solve, Submission
    from models.challenge import Challenge
    from models.hint import HintUnlock
    from datetime import datetime
    
    user = User.objects(id=user_id).first_or_404()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get all solves with challenges
    solves_query = Solve.objects(user=user).order_by('-solved_at')
    
    solves_pagination = solves_query.paginate(page=page, per_page=per_page)
    
    # Get hints unlocked by this user
    hints_unlocked = HintUnlock.objects(user=user).order_by('-unlocked_at')
    
    # Get total stats
    total_solves = Solve.objects(user=user, challenge__ne=None).count()
    total_submissions = Submission.objects(user=user).count()
    total_hints = hints_unlocked.count()
    total_score = user.get_score()
    
    return render_template('admin/user_activity.html', 
                          user=user,
                          solves_pagination=solves_pagination,
                          hints_unlocked=hints_unlocked,
                          total_solves=total_solves,
                          total_submissions=total_submissions,
                          total_hints=total_hints,
                          total_score=total_score,
                          now=datetime.utcnow())


@admin_bp.route('/teams/<string:team_id>/solves', methods=['GET'])
@login_required
@admin_required
def get_team_solves(team_id):
    """Get solve history for a team including manual adjustments"""
    from models.submission import Solve
    from models.challenge import Challenge
    
    team = Team.objects(id=team_id).first_or_404()
    
    solves = Solve.objects(team=team).order_by('-solved_at')
    
    solve_list = []
    for solve in solves:
        challenge = solve.challenge
        solve_list.append({
            'challenge_name': challenge.name if challenge else None,
            'points': solve.points_earned,
            'solved_at': solve.solved_at.isoformat(),
            'is_adjustment': challenge is None,
            'reason': None
        })
    
    return jsonify({
        'success': True,
        'solves': solve_list
    })


# Notifications management
@admin_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_notifications():
    """Admin page to create and send notifications to all users"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()

        if not title or not body:
            flash('Title and body are required to send a notification', 'error')
            return redirect(url_for('admin.manage_notifications'))
        # Read play_sound option
        play_sound = request.form.get('play_sound') in ('true', 'on', '1')

        # Create notification record (persist whether recipients should play sound)
        notif = Notification(title=title, body=body, sent_by=current_user, play_sound=play_sound)
        notif.save()

        # Broadcast via websocket
        try:
            WebSocketService.emit_notification(notif.to_dict())
        except Exception as e:
            current_app.logger.exception('Failed to emit notification via websocket')

        flash('Notification sent to all connected users', 'success')
        return redirect(url_for('admin.manage_notifications'))

    # GET: list recent notifications
    notifications = Notification.objects.order_by('-created_at').limit(50)
    return render_template('admin/notifications.html', notifications=notifications)


# Settings
@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    """Platform settings"""
    from models.settings import Settings
    
    if request.method == 'POST':
        # This would update configuration
        # For now, just show success message
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('admin.settings'))
    
    import flask
    
    # Get CTF control settings
    ctf_settings = {
        'start_time': Settings.get('ctf_start_time'),
        'end_time': Settings.get('ctf_end_time'),
        'is_paused': Settings.get('ctf_paused', False),
        'status': Settings.get_ctf_status()
    }
    
    # Get all settings
    all_settings = Settings.get_all()
    
    return render_template('admin/settings.html', 
                         flask_version=flask.__version__,
                         get_flask_version=lambda: flask.__version__,
                         ctf_settings=ctf_settings,
                         settings=all_settings)


@admin_bp.route('/settings/event-config', methods=['POST'])
@login_required
@admin_required
def update_event_config():
    """Update event configuration (name, logo, description)"""
    from models.settings import Settings
    import os
    from werkzeug.utils import secure_filename
    
    try:
        # Update CTF name
        ctf_name = request.form.get('ctf_name', '').strip()
        if ctf_name:
            Settings.set('ctf_name', ctf_name, 'string', 'Name of the CTF event')
        
        # Update CTF description
        ctf_description = request.form.get('ctf_description', '').strip()
        if ctf_description:
            Settings.set('ctf_description', ctf_description, 'string', 'Description of the CTF event')
        
        # Update registration and team mode settings
        allow_registration = 'allow_registration' in request.form
        Settings.set('allow_registration', allow_registration, 'bool', 'Allow new user registrations')
        
        teams_enabled = 'teams_enabled' in request.form
        Settings.set('teams_enabled', teams_enabled, 'bool', 'Enable teams feature (for solo competitions)')
        
        team_mode = 'team_mode' in request.form
        Settings.set('team_mode', team_mode, 'bool', 'Enable team-based CTF mode')
        
        # Update scoreboard visibility
        scoreboard_visible = 'scoreboard_visible' in request.form
        Settings.set('scoreboard_visible', scoreboard_visible, 'bool', 'Show scoreboard to users')
        
        # Update first blood bonus
        first_blood_bonus = request.form.get('first_blood_bonus', '0')
        try:
            first_blood_bonus = int(first_blood_bonus)
            Settings.set('first_blood_bonus', first_blood_bonus, 'int', 'Bonus points for first blood')
        except ValueError:
            pass  # Ignore invalid values
        
        # Update decay function
        decay_function = request.form.get('decay_function', 'logarithmic')
        if decay_function in ['logarithmic', 'parabolic']:
            Settings.set('decay_function', decay_function, 'string', 'Dynamic scoring decay function')
        
        # Handle logo upload
        if 'ctf_logo' in request.files:
            logo_file = request.files['ctf_logo']
            if logo_file and logo_file.filename:
                from flask import current_app
                
                # Use /var/uploads/logos (volume-mounted writable directory)
                uploads_dir = '/var/uploads/logos'
                
                # Create uploads directory if it doesn't exist
                os.makedirs(uploads_dir, exist_ok=True)
                
                # Secure the filename
                filename = secure_filename(logo_file.filename)
                
                # Add timestamp to avoid conflicts
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                name, ext = os.path.splitext(filename)
                filename = f'ctf_logo_{timestamp}{ext}'
                
                # Save the file
                filepath = os.path.join(uploads_dir, filename)
                logo_file.save(filepath)
                
                # Store relative path in settings
                Settings.set('ctf_logo', filename, 'string', 'Path to CTF logo image')
        
        flash('Event configuration updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating configuration: {str(e)}', 'error')
    
    return redirect(url_for('admin.settings'))


@admin_bp.route('/settings/background-theme', methods=['POST'])
@login_required
@admin_required
def update_background_theme():
    """Update custom background theme"""
    from models.settings import Settings
    import re
    
    try:
        enabled = 'custom_background_enabled' in request.form
        Settings.set('custom_background_enabled', enabled, 'bool', 'Enable custom background theme')
        
        if enabled:
            css = request.form.get('custom_background_css', '').strip()
            
            # Security: Only allow background-related CSS properties
            # NOTE: This feature is restricted to ADMINS ONLY. Users cannot modify this setting.
            allowed_properties = [
                'background', 'background-color', 'background-image', 
                'background-size', 'background-position', 'background-repeat',
                'background-attachment', 'animation', '@keyframes'
            ]
            
            # Very basic validation - check if it contains only allowed properties
            # This is a simple check, not a full CSS parser
            if css:
                # Remove comments
                css_clean = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
                
                # Check for potentially dangerous content
                # Enhanced blacklist for XSS prevention
                dangerous_patterns = [
                    r'<script', r'javascript:', r'onerror', r'onload',
                    r'eval\(', r'expression\(', r'import\s+["\']',
                    r'behavior:', r'binding:', r'-moz-binding'
                ]
                
                for pattern in dangerous_patterns:
                    if re.search(pattern, css_clean, re.IGNORECASE):
                        flash('Invalid CSS: Potentially dangerous content detected', 'error')
                        return redirect(url_for('admin.settings'))
                
                Settings.set('custom_background_css', css, 'string', 'Custom background CSS')
            else:
                Settings.set('custom_background_css', '', 'string', 'Custom background CSS')
        
        flash('Background theme updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating background theme: {str(e)}', 'error')
    
    return redirect(url_for('admin.settings'))


@admin_bp.route('/update-system-settings', methods=['POST'])
@login_required
@admin_required
def update_system_settings():
    """Update system settings (timezone and backup frequency)"""
    from models.settings import Settings
    from services.backup_scheduler import backup_scheduler
    
    try:
        # Update timezone
        timezone = request.form.get('timezone', 'UTC')
        Settings.set('timezone', timezone, 'string', 'Platform timezone')
        
        # Update backup frequency
        backup_frequency = request.form.get('backup_frequency', 'disabled')
        old_frequency = Settings.get('backup_frequency', 'disabled')
        Settings.set('backup_frequency', backup_frequency, 'string', 'Automatic backup frequency')
        
        # Clear last auto backup time if disabling backups
        if backup_frequency == 'disabled':
            Settings.set('last_auto_backup', None, 'datetime', 'Last automatic backup timestamp')
        
        # Reschedule backups if frequency changed
        if backup_frequency != old_frequency and backup_scheduler is not None:
            backup_scheduler.reschedule()
        
        flash('System settings updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating system settings: {str(e)}', 'error')
    
    return redirect(url_for('admin.settings'))


# CTF Control
@admin_bp.route('/ctf-control', methods=['GET', 'POST'])
@login_required
@admin_required
def ctf_control():
    """CTF control panel for scheduling and pausing"""
    from models.settings import Settings
    from datetime import datetime
    import pytz
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'set_times':
            start_time_str = request.form.get('start_time')
            end_time_str = request.form.get('end_time')
            
            # Get platform timezone
            tz_name = Settings.get('timezone', 'UTC')
            try:
                tz = pytz.timezone(tz_name)
            except pytz.UnknownTimeZoneError:
                tz = pytz.UTC
            
            if start_time_str:
                try:
                    # Parse as naive datetime (user input is in platform timezone)
                    start_time_naive = datetime.fromisoformat(start_time_str)
                    # Localize to platform timezone
                    start_time_aware = tz.localize(start_time_naive)
                    # Convert to UTC for storage
                    start_time_utc = start_time_aware.astimezone(pytz.UTC).replace(tzinfo=None)
                    Settings.set('ctf_start_time', start_time_utc, 'datetime', 'CTF start time')
                    flash('CTF start time set successfully!', 'success')
                except ValueError:
                    flash('Invalid start time format', 'error')
            
            if end_time_str:
                try:
                    # Parse as naive datetime (user input is in platform timezone)
                    end_time_naive = datetime.fromisoformat(end_time_str)
                    # Localize to platform timezone
                    end_time_aware = tz.localize(end_time_naive)
                    # Convert to UTC for storage
                    end_time_utc = end_time_aware.astimezone(pytz.UTC).replace(tzinfo=None)
                    Settings.set('ctf_end_time', end_time_utc, 'datetime', 'CTF end time')
                    flash('CTF end time set successfully!', 'success')
                except ValueError:
                    flash('Invalid end time format', 'error')
        
        elif action == 'clear_times':
            Settings.set('ctf_start_time', None, 'datetime')
            Settings.set('ctf_end_time', None, 'datetime')
            flash('CTF schedule cleared - CTF is now always running', 'success')
        
        elif action == 'pause':
            Settings.set('ctf_paused', True, 'bool', 'CTF paused status')
            flash('CTF paused - Submissions disabled', 'warning')
        
        elif action == 'resume':
            Settings.set('ctf_paused', False, 'bool', 'CTF paused status')
            flash('CTF resumed - Submissions enabled', 'success')
        
        return redirect(url_for('admin.ctf_control'))
    
    # Get current settings
    ctf_settings = {
        'start_time': Settings.get('ctf_start_time'),
        'end_time': Settings.get('ctf_end_time'),
        'is_paused': Settings.get('ctf_paused', False),
        'status': Settings.get_ctf_status()
    }
    
    return render_template('admin/ctf_control.html', ctf_settings=ctf_settings)


# Hint Management
@admin_bp.route('/hints/<string:hint_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_hint(hint_id):
    """Delete a hint"""
    hint = Hint.objects(id=hint_id).first_or_404()
    challenge_id = hint.challenge.id
    
    hint.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({
        'success': True,
        'message': 'Hint deleted successfully'
    })


# Challenge Branching Management
@admin_bp.route('/branching')
@login_required
@admin_required
def manage_branching():
    """Manage challenge branching and prerequisites"""
    challenges = Challenge.objects.order_by('name')
    return render_template('admin/branching.html', challenges=challenges)


@admin_bp.route('/branching/flags', methods=['GET'])
@login_required
@admin_required
def get_flags():
    """Get all challenge flags"""
    from models.branching import ChallengeFlag
    
    flags = ChallengeFlag.objects
    flags_data = []
    
    for flag in flags:
        flag_dict = flag.to_dict(include_value=True)
        flag_dict['challenge_name'] = flag.challenge.name if flag.challenge else None
        flag_dict['unlocks_challenge_name'] = flag.unlocks_challenge.name if flag.unlocks_challenge else None
        flags_data.append(flag_dict)
    
    return jsonify({'success': True, 'flags': flags_data})


@admin_bp.route('/branching/flags', methods=['POST'])
@login_required
@admin_required
def add_flag():
    """Add a new flag to a challenge"""
    from models.branching import ChallengeFlag
    import re
    
    challenge_id = request.form.get('challenge_id')
    flag_value = request.form.get('flag_value', '').strip()
    flag_label = request.form.get('flag_label', '').strip()
    unlocks_challenge_id = request.form.get('unlocks_challenge_id')
    points_override = request.form.get('points_override')
    is_case_sensitive = request.form.get('is_case_sensitive', '1') == '1'
    is_regex = request.form.get('is_regex', '0') == '1'
    
    if not challenge_id or not flag_value:
        return jsonify({'success': False, 'message': 'Challenge and flag value are required'}), 400
    
    # Validate challenge exists
    challenge = Challenge.objects(id=challenge_id).first()
    if not challenge:
        return jsonify({'success': False, 'message': 'Challenge not found'}), 404
    
    # For regex flags, validate the pattern
    if is_regex:
        try:
            re.compile(flag_value)
        except re.error as e:
            return jsonify({'success': False, 'message': f'Invalid regex pattern: {str(e)}'}), 400
    
    # Validate unlocks_challenge exists if provided
    unlocks_challenge = None
    if unlocks_challenge_id:
        unlocks_challenge = Challenge.objects(id=unlocks_challenge_id).first()
        if not unlocks_challenge:
            return jsonify({'success': False, 'message': 'Unlocks challenge not found'}), 404
    
    # Convert points_override
    if points_override and points_override.strip():
        try:
            points_override = int(points_override)
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid points override'}), 400
    else:
        points_override = None
    
    # Create flag
    new_flag = ChallengeFlag(
        challenge=challenge,
        flag_value=flag_value,
        flag_label=flag_label if flag_label else None,
        unlocks_challenge=unlocks_challenge,
        points_override=points_override,
        is_case_sensitive=is_case_sensitive,
        is_regex=is_regex
    )
    
    new_flag.save()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'Flag added successfully', 'flag': new_flag.to_dict(include_value=True)})


@admin_bp.route('/branching/flags/<string:flag_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_flag(flag_id):
    """Delete a challenge flag"""
    from models.branching import ChallengeFlag
    
    flag = ChallengeFlag.objects(id=flag_id).first_or_404()
    challenge_id = flag.challenge.id
    
    flag.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'Flag deleted successfully'})


@admin_bp.route('/branching/prerequisites', methods=['GET'])
@login_required
@admin_required
def get_prerequisites():
    """Get all challenge prerequisites"""
    from models.branching import ChallengePrerequisite
    
    prerequisites = ChallengePrerequisite.objects
    prereqs_data = []
    
    for prereq in prerequisites:
        prereq_dict = prereq.to_dict()
        prereq_dict['challenge_name'] = prereq.challenge.name if prereq.challenge else None
        prereq_dict['prerequisite_name'] = prereq.prerequisite_challenge.name if prereq.prerequisite_challenge else None
        prereqs_data.append(prereq_dict)
    
    return jsonify({'success': True, 'prerequisites': prereqs_data})


@admin_bp.route('/branching/prerequisites', methods=['POST'])
@login_required
@admin_required
def add_prerequisite():
    """Add a prerequisite to a challenge"""
    from models.branching import ChallengePrerequisite
    
    challenge_id = request.form.get('challenge_id')
    prerequisite_challenge_id = request.form.get('prerequisite_challenge_id')
    
    if not challenge_id or not prerequisite_challenge_id:
        return jsonify({'success': False, 'message': 'Both challenge and prerequisite are required'}), 400
    
    # Check if same challenge
    if challenge_id == prerequisite_challenge_id:
        return jsonify({'success': False, 'message': 'A challenge cannot be a prerequisite of itself'}), 400
    
    # Validate both challenges exist
    challenge = Challenge.objects(id=challenge_id).first()
    prereq_challenge = Challenge.objects(id=prerequisite_challenge_id).first()
    
    if not challenge or not prereq_challenge:
        return jsonify({'success': False, 'message': 'Challenge(s) not found'}), 404
    
    # Check if prerequisite already exists
    existing = ChallengePrerequisite.objects(
        challenge=challenge,
        prerequisite_challenge=prereq_challenge
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'This prerequisite already exists'}), 400
    
    # TODO: Check for circular dependencies
    
    # Create prerequisite
    new_prereq = ChallengePrerequisite(
        challenge=challenge,
        prerequisite_challenge=prereq_challenge
    )
    
    new_prereq.save()
    
    # Automatically set unlock_mode to 'prerequisite' and hide the challenge
    if challenge.unlock_mode != 'prerequisite':
        challenge.unlock_mode = 'prerequisite'
        challenge.is_hidden = True
        # When a challenge is hidden due to prerequisites, also mark it not visible
        # so normal users won't see it in the public challenges list.
        challenge.is_visible = False
        challenge.save()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({
        'success': True, 
        'message': 'Prerequisite added successfully. Challenge is now hidden until prerequisite is solved.',
        'prerequisite': new_prereq.to_dict()
    })


@admin_bp.route('/branching/prerequisites/<string:prereq_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_prerequisite(prereq_id):
    """Delete a challenge prerequisite"""
    from models.branching import ChallengePrerequisite
    
    prereq = ChallengePrerequisite.objects(id=prereq_id).first_or_404()
    challenge_id = prereq.challenge.id
    
    prereq.delete()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'Prerequisite deleted successfully'})


@admin_bp.route('/branching/unlock-mode/<string:challenge_id>', methods=['PUT'])
@login_required
@admin_required
def update_unlock_mode(challenge_id):
    """Update challenge unlock mode and hidden status"""
    challenge = Challenge.objects(id=challenge_id).first_or_404()
    
    data = request.get_json()
    unlock_mode = data.get('unlock_mode')
    is_hidden = data.get('is_hidden', False)
    
    if unlock_mode not in ['none', 'prerequisite', 'flag_unlock']:
        return jsonify({'success': False, 'message': 'Invalid unlock mode'}), 400
    
    challenge.unlock_mode = unlock_mode
    # Persist hidden state and ensure visibility matches hidden flag
    challenge.is_hidden = bool(is_hidden)
    # If admin marks challenge as hidden, it should not be visible to regular users.
    # Conversely, un-hiding should make it visible again by default.
    challenge.is_visible = not bool(is_hidden)
    
    challenge.save()
    
    cache_service.invalidate_challenge(challenge_id)
    
    return jsonify({'success': True, 'message': 'Unlock mode updated successfully'})


@admin_bp.route('/branching/challenges/<string:challenge_id>/flags', methods=['GET'])
@login_required
@admin_required
def get_challenge_flags(challenge_id):
    """Get all flags for a specific challenge"""
    from models.branching import ChallengeFlag
    
    flags = ChallengeFlag.objects(challenge=challenge_id)
    flags_data = [flag.to_dict(include_value=True) for flag in flags]
    
    return jsonify({'success': True, 'flags': flags_data})


@admin_bp.route('/branching/flags/<string:flag_id>/unlock', methods=['PUT'])
@login_required
@admin_required
def update_flag_unlock(flag_id):
    """Update which challenge a flag unlocks"""
    from models.branching import ChallengeFlag
    
    flag = ChallengeFlag.objects(id=flag_id).first_or_404()
    data = request.get_json()
    unlocks_challenge_id = data.get('unlocks_challenge_id')
    
    # Validate unlocks_challenge exists if provided
    if unlocks_challenge_id:
        unlocks_challenge = Challenge.objects(id=unlocks_challenge_id).first()
        if not unlocks_challenge:
            return jsonify({'success': False, 'message': 'Target challenge not found'}), 404
        
        # Auto-configure the target challenge for flag unlocking
        if unlocks_challenge.unlock_mode != 'flag_unlock':
            unlocks_challenge.unlock_mode = 'flag_unlock'
            unlocks_challenge.is_hidden = True
            # Hide the target challenge from public view until unlocked
            unlocks_challenge.is_visible = False
            unlocks_challenge.save()
    
    flag.unlocks_challenge = unlocks_challenge if unlocks_challenge_id else None
    flag.save()
    
    cache_service.invalidate_challenge(flag.challenge.id)
    if unlocks_challenge_id:
        cache_service.invalidate_challenge(unlocks_challenge_id)
    
    message = 'Branching configured successfully'
    if unlocks_challenge_id:
        message += '. Target challenge is now hidden until this flag is submitted.'
    
    return jsonify({'success': True, 'message': message})


@admin_bp.route('/branching/connections', methods=['GET'])
@login_required
@admin_required
def get_branching_connections():
    """Get all branching connections (flags that unlock challenges)"""
    from models.branching import ChallengeFlag
    
    flags = ChallengeFlag.objects(unlocks_challenge__ne=None)
    connections = []
    
    for flag in flags:
        connections.append({
            'flag_id': str(flag.id),
            'parent_challenge': flag.challenge.name if flag.challenge else 'Unknown',
            'parent_challenge_id': str(flag.challenge.id) if flag.challenge else None,
            'flag_value': flag.flag_value,
            'flag_label': flag.flag_label,
            'child_challenge': flag.unlocks_challenge.name if flag.unlocks_challenge else 'Unknown',
            'child_challenge_id': str(flag.unlocks_challenge.id) if flag.unlocks_challenge else None
        })
    
    return jsonify({'success': True, 'connections': connections})


@admin_bp.route('/hint-logs')
@login_required
@admin_required
def hint_logs():
    """View hint unlock logs"""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Get all hint unlocks with pagination
    hint_unlocks = HintUnlock.objects.order_by('-unlocked_at').paginate(
        page=page, per_page=per_page
    )
    
    return render_template('admin/hint_logs.html', hint_unlocks=hint_unlocks)


@admin_bp.route('/hint-logs/api')
@login_required
@admin_required
def hint_logs_api():
    """Get hint unlock logs as JSON"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    user_id = request.args.get('user_id')
    team_id = request.args.get('team_id')
    challenge_id = request.args.get('challenge_id')
    
    query = HintUnlock.objects
    
    # Apply filters
    if user_id:
        query = query.filter(user=user_id)
    if team_id:
        query = query.filter(team=team_id)
    if challenge_id:
        # Find hints for this challenge first
        hints = Hint.objects(challenge=challenge_id)
        query = query.filter(hint__in=hints)
    
    hint_unlocks = query.order_by('-unlocked_at').paginate(
        page=page, per_page=per_page
    )
    
    logs = []
    for unlock in hint_unlocks.items:
        hint = unlock.hint
        challenge = hint.challenge if hint else None
        user = unlock.user
        team = unlock.team
        
        logs.append({
            'id': str(unlock.id),
            'user': user.username if user else 'Unknown',
            'user_id': str(unlock.user.id) if unlock.user else None,
            'team': team.name if team else None,
            'team_id': str(unlock.team.id) if unlock.team else None,
            'challenge': challenge.name if challenge else 'Unknown',
            'challenge_id': str(challenge.id) if challenge else None,
            'hint_order': hint.order if hint else 0,
            'cost': unlock.cost_paid,
            'unlocked_at': unlock.unlocked_at.isoformat()
        })
    
    return jsonify({
        'success': True,
        'logs': logs,
        'total': hint_unlocks.total,
        'pages': hint_unlocks.pages,
        'current_page': hint_unlocks.page
    })


# ==================== Flag Abuse Monitoring ====================

@admin_bp.route('/flag-abuse')
@login_required
@admin_required
def flag_abuse():
    """Flag abuse attempts monitoring page"""
    from models.flag_abuse import FlagAbuseAttempt
    from models.challenge import Challenge
    from models.user import User
    from models.team import Team
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Filters
    challenge_id = request.args.get('challenge_id')
    team_id = request.args.get('team_id')
    user_id = request.args.get('user_id')
    severity = request.args.get('severity', type=str)
    
    # Build query
    query = FlagAbuseAttempt.objects
    
    if challenge_id:
        query = query.filter(challenge=challenge_id)
    if team_id:
        query = query.filter(team=team_id)
    if user_id:
        query = query.filter(user=user_id)
    if severity:
        query = query.filter(severity=severity)
    
    # Order by most recent first
    query = query.order_by('-timestamp')
    
    # Paginate
    attempts = query.paginate(page=page, per_page=per_page)
    
    # Get filter options
    challenges = Challenge.objects.order_by('name')
    teams = Team.objects.order_by('name')
    
    # Get statistics
    total_attempts = FlagAbuseAttempt.objects.count()
    attempts_today = FlagAbuseAttempt.objects(
        timestamp__gte=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ).count()
    unique_users = len(FlagAbuseAttempt.objects.distinct('user'))
    unique_teams = len(FlagAbuseAttempt.objects(team__ne=None).distinct('team'))
    
    # Get repeat offenders (teams with multiple attempts)
    repeat_offenders = FlagAbuseAttempt.get_repeat_offenders(limit=10, min_attempts=3)
    
    # Count by severity
    severity_counts = {
        'warning': FlagAbuseAttempt.objects(severity='warning').count(),
        'suspicious': FlagAbuseAttempt.objects(severity='suspicious').count(),
        'critical': FlagAbuseAttempt.objects(severity='critical').count()
    }
    
    return render_template('admin/flag_abuse.html',
        attempts=attempts.items,
        pagination=attempts,
        challenges=challenges,
        teams=teams,
        total_attempts=total_attempts,
        attempts_today=attempts_today,
        unique_users=unique_users,
        unique_teams=unique_teams,
        repeat_offenders=repeat_offenders,
        severity_counts=severity_counts,
        filters={
            'challenge_id': challenge_id,
            'team_id': team_id,
            'user_id': user_id,
            'severity': severity
        }
    )


@admin_bp.route('/flag-abuse/<string:attempt_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_flag_abuse_attempt(attempt_id):
    """Delete a flag abuse attempt record"""
    from models.flag_abuse import FlagAbuseAttempt
    
    attempt = FlagAbuseAttempt.objects.get_or_404(id=attempt_id)
    attempt.delete()
    
    flash('Flag abuse record deleted successfully', 'success')
    return redirect(url_for('admin.flag_abuse'))


@admin_bp.route('/flag-abuse/clear-all', methods=['POST'])
@login_required
@admin_required
def clear_all_flag_abuse():
    """Clear all flag abuse attempt records"""
    from models.flag_abuse import FlagAbuseAttempt
    
    count = FlagAbuseAttempt.objects.delete()
    
    flash(f'Cleared {count} flag abuse records', 'success')
    return redirect(url_for('admin.flag_abuse'))


# ==================== Backup Management ====================

@admin_bp.route('/backups')
@login_required
@admin_required
def backups():
    """Backup management page"""
    return render_template('admin/backups.html')


@admin_bp.route('/backups/api/list')
@login_required
@admin_required
def list_backups():
    """List all available backups (stored in uploads directory)"""
    import json
    import os
    from pathlib import Path
    from datetime import datetime
    
    try:
        # Store backups in the uploads directory under 'backups' folder
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backups = []
        
        if backup_dir.exists():
            # Look for .json.gz files (MongoDB backups) and legacy .sql.gz files
            for backup_file in sorted(list(backup_dir.glob('backup_*.json.gz')) + list(backup_dir.glob('backup_*.sql.gz')), reverse=True):
                is_legacy = backup_file.suffix == '.gz' and backup_file.with_suffix('').suffix == '.sql'
                ext = '.sql.gz' if is_legacy else '.json.gz'
                backup_name = backup_file.name.replace(ext, '')
                
                # Try to read metadata if it exists
                metadata_file = backup_dir / f'{backup_name}.json'
                if metadata_file.exists():
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            backups.append(metadata)
                    except json.JSONDecodeError:
                        # Use file modification time as fallback, convert to ISO format
                        timestamp = datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat()
                        backups.append({
                            'backup_name': backup_name,
                            'timestamp': timestamp,
                            'size_mb': round(backup_file.stat().st_size / (1024 * 1024), 2),
                            'type': 'legacy' if is_legacy else 'mongodb'
                        })
                else:
                    # Use file modification time as fallback, convert to ISO format
                    timestamp = datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat()
                    backups.append({
                        'backup_name': backup_name,
                        'timestamp': timestamp,
                        'size_mb': round(backup_file.stat().st_size / (1024 * 1024), 2),
                        'type': 'legacy' if is_legacy else 'mongodb'
                    })
        
        return jsonify({'success': True, 'backups': backups})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/backups/api/create', methods=['POST'])
@login_required
@admin_required
def create_backup():
    """Create a manual database backup"""
    import gzip
    import json
    from datetime import datetime
    from pathlib import Path
    
    try:
        # Create backup directory
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate backup name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'backup_{timestamp}'
        backup_file = backup_dir / f'{backup_name}.json.gz'
        
        # Determine optional components requested (JSON body or form)
        include_uploads = False
        include_redis = False
        try:
            data = request.get_json(silent=True) or {}
            include_uploads = bool(data.get('include_uploads'))
            include_redis = bool(data.get('include_redis'))
        except Exception:
            include_uploads = request.form.get('include_uploads') == 'on'
            include_redis = request.form.get('include_redis') == 'on'

        # Export database to JSON
        backup_data = {}
        
        # List of models to backup
        from models.user import User
        from models.team import Team
        from models.challenge import Challenge, ChallengePrerequisite
        from models.hint import Hint, HintUnlock
        from models.submission import Submission
        from models.notification import Notification
        from models.notification_read import NotificationRead
        from models.settings import Settings, DockerSettings
        from models.file import File
        from models.container import ContainerInstance
        from models.flag_abuse import FlagAbuseAttempt
        
        model_map = {
            'users': User,
            'teams': Team,
            'challenges': Challenge,
            'challenge_prerequisites': ChallengePrerequisite,
            'hints': Hint,
            'hint_unlocks': HintUnlock,
            'submissions': Submission,
            'notifications': Notification,
            'notification_reads': NotificationRead,
            'settings': Settings,
            'docker_settings': DockerSettings,
            'files': File,
            'containers': ContainerInstance,
            'flag_abuse_attempts': FlagAbuseAttempt
        }
        
        total_records = 0
        for name, model in model_map.items():
            docs = model.objects.all()
            # Use to_json() to handle ObjectId and DateTime serialization, then parse back to dict
            backup_data[name] = [json.loads(doc.to_json()) for doc in docs]
            total_records += len(backup_data[name])
        
        # Write compressed backup
        with gzip.open(backup_file, 'wt', encoding='utf-8') as f:
            json.dump(backup_data, f)
        
        # Prepare components metadata
        components = {'database': True, 'uploads': False, 'redis': False}
        sizes = {
            'database_mb': round(backup_file.stat().st_size / (1024 * 1024), 2),
            'uploads_mb': 0,
            'redis_mb': 0
        }

        # Include uploads if requested
        if include_uploads:
            try:
                uploads_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads'))
                uploads_archive = backup_dir / f"{backup_name}_uploads.tar.gz"
                if uploads_dir.exists():
                    import tarfile
                    with tarfile.open(uploads_archive, 'w:gz') as tar:
                        tar.add(uploads_dir, arcname='uploads')
                    components['uploads'] = True
                    sizes['uploads_mb'] = round(uploads_archive.stat().st_size / (1024 * 1024), 2)
            except Exception as e:
                current_app.logger.warning(f"Failed to include uploads in manual backup: {e}")

        # Include redis snapshot if requested (best-effort)
        if include_redis:
            try:
                import redis as redislib
                redis_url = current_app.config.get('REDIS_URL')
                if redis_url:
                    r = redislib.from_url(redis_url)
                    try:
                        r.bgsave()
                    except Exception:
                        try:
                            r.save()
                        except Exception:
                            pass

                    try:
                        cfg = r.config_get('dir')
                        dirpath = cfg.get('dir') if isinstance(cfg, dict) else None
                        dbfile = r.config_get('dbfilename')
                        filename = dbfile.get('dbfilename') if isinstance(dbfile, dict) else None
                        if dirpath and filename:
                            dump_path = Path(dirpath) / filename
                            if dump_path.exists():
                                import shutil
                                target = backup_dir / f"{backup_name}_redis.rdb"
                                shutil.copy2(dump_path, target)
                                components['redis'] = True
                                sizes['redis_mb'] = round(target.stat().st_size / (1024 * 1024), 2)
                    except Exception:
                        current_app.logger.debug('Could not copy redis dump file; skipping')
            except Exception as e:
                current_app.logger.warning(f"Failed to include redis in manual backup: {e}")

        # Create metadata
        metadata = {
            'backup_name': backup_name,
            'timestamp': datetime.now().isoformat(),
            'database': 'mongodb',
            'collections': len(model_map),
            'records': total_records,
            'size_mb': sizes['database_mb'],
            'components': components,
            'sizes': sizes
        }
        
        metadata_file = backup_dir / f'{backup_name}.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        return jsonify({
            'success': True,
            'message': 'Backup created successfully',
            'backup': metadata
        })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/backups/api/restore', methods=['POST'])
@login_required
@admin_required
def restore_backup():
    """Restore from a backup"""
    import gzip
    import json
    from pathlib import Path
    from bson import json_util
    
    data = request.get_json()
    backup_name = data.get('backup_name')
    
    if not backup_name or not backup_name.startswith('backup_'):
        return jsonify({'success': False, 'error': 'Invalid backup name'})
    
    try:
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        
        # Check for JSON backup first
        backup_file = backup_dir / f'{backup_name}.json.gz'
        is_legacy = False
        
        if not backup_file.exists():
            # Check for legacy SQL backup
            backup_file = backup_dir / f'{backup_name}.sql.gz'
            is_legacy = True
            
        if not backup_file.exists():
            return jsonify({'success': False, 'error': 'Backup file not found'})
            
        if is_legacy:
            return jsonify({'success': False, 'error': 'Legacy SQL backups cannot be restored to MongoDB. Please use a JSON backup.'})
        
        # Read backup file
        with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
            # Use json_util to parse MongoDB extended JSON (preserves ObjectIds, Dates)
            backup_data = json_util.loads(f.read())
            
        # List of models to restore
        from models.user import User
        from models.team import Team
        from models.challenge import Challenge, ChallengePrerequisite
        from models.hint import Hint, HintUnlock
        from models.submission import Submission
        from models.notification import Notification
        from models.notification_read import NotificationRead
        from models.settings import Settings, DockerSettings
        from models.file import File
        from models.container import ContainerInstance
        from models.flag_abuse import FlagAbuseAttempt
        
        model_map = {
            'users': User,
            'teams': Team,
            'challenges': Challenge,
            'challenge_prerequisites': ChallengePrerequisite,
            'hints': Hint,
            'hint_unlocks': HintUnlock,
            'submissions': Submission,
            'notifications': Notification,
            'notification_reads': NotificationRead,
            'settings': Settings,
            'docker_settings': DockerSettings,
            'files': File,
            'containers': ContainerInstance,
            'flag_abuse_attempts': FlagAbuseAttempt
        }
        
        restored_counts = {}
        
        # Restore each collection
        for name, docs in backup_data.items():
            if name in model_map:
                model = model_map[name]
                # Clear existing data
                model.objects.delete()
                
                if docs:
                    # Bulk insert
                    # docs are already BSON-compatible dicts thanks to json_util
                    model._get_collection().insert_many(docs)
                    restored_counts[name] = len(docs)
        
        # Clear all caches
        from services.cache import cache_service
        cache_service.clear_all()
        
        return jsonify({
            'success': True,
            'message': f'Backup restored successfully! Restored {sum(restored_counts.values())} records across {len(restored_counts)} collections.',
            'details': restored_counts
        })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/backups/api/delete', methods=['POST'])
@login_required
@admin_required
def delete_backup():
    """Delete a backup"""
    from pathlib import Path
    
    data = request.get_json()
    backup_name = data.get('backup_name')
    
    if not backup_name or not backup_name.startswith('backup_'):
        return jsonify({'success': False, 'error': 'Invalid backup name'})
    
    try:
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        
        # Try to find the file (json.gz or sql.gz)
        backup_file = backup_dir / f'{backup_name}.json.gz'
        if not backup_file.exists():
            backup_file = backup_dir / f'{backup_name}.sql.gz'
            
        metadata_file = backup_dir / f'{backup_name}.json'
        
        # Delete files
        if backup_file.exists():
            backup_file.unlink()
        if metadata_file.exists():
            metadata_file.unlink()
        
        return jsonify({'success': True, 'message': 'Backup deleted successfully'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@admin_bp.route('/backups/api/download/<backup_name>')
@login_required
@admin_required
def download_backup(backup_name):
    """Download a backup file"""
    from flask import send_file
    from pathlib import Path
    
    if not backup_name.startswith('backup_'):
        flash('Invalid backup name', 'error')
        return redirect(url_for('admin.backups'))
    
    try:
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        
        # Try to find the file (json.gz or sql.gz)
        backup_file = backup_dir / f'{backup_name}.json.gz'
        filename = f'{backup_name}.json.gz'
        
        if not backup_file.exists():
            backup_file = backup_dir / f'{backup_name}.sql.gz'
            filename = f'{backup_name}.sql.gz'
        
        if not backup_file.exists():
            flash('Backup file not found', 'error')
            return redirect(url_for('admin.backups'))
        
        return send_file(
            backup_file,
            as_attachment=True,
            download_name=filename,
            mimetype='application/gzip'
        )
        
    except Exception as e:
        flash(f'Download failed: {str(e)}', 'error')
        return redirect(url_for('admin.backups'))


@admin_bp.route('/backups/api/upload', methods=['POST'])
@login_required
@admin_required
def upload_backup():
    """Upload a backup file for restoration"""
    from pathlib import Path
    from datetime import datetime
    import json
    
    try:
        if 'backup_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['backup_file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        if not (file.filename.endswith('.sql.gz') or file.filename.endswith('.json.gz')):
            return jsonify({'success': False, 'error': 'Invalid file type. Must be .json.gz or .sql.gz'})
        
        # Save to backups directory
        backup_dir = Path(current_app.config.get('UPLOAD_FOLDER', 'static/uploads')) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate name if not already in backup format
        if file.filename.startswith('backup_'):
            backup_name = file.filename.replace('.sql.gz', '').replace('.json.gz', '')
        else:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f'backup_uploaded_{timestamp}'
        
        ext = '.sql.gz' if file.filename.endswith('.sql.gz') else '.json.gz'
        backup_file = backup_dir / f'{backup_name}{ext}'
        file.save(backup_file)
        
        # Create metadata
        metadata = {
            'backup_name': backup_name,
            'timestamp': datetime.now().isoformat(),
            'uploaded': True,
            'original_filename': file.filename,
            'size_mb': backup_file.stat().st_size / (1024 * 1024),
            'type': 'legacy' if ext == '.sql.gz' else 'mongodb'
        }
        
        metadata_file = backup_dir / f'{backup_name}.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return jsonify({
            'success': True,
            'message': 'Backup uploaded successfully',
            'backup': metadata
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ==================== Docker Container Management ====================

@admin_bp.route('/docker/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def docker_settings():
    """Configure Docker connection and settings"""
    from models.settings import DockerSettings
    
    settings = DockerSettings.get_config()
    
    if request.method == 'POST':
        # Update basic settings
        settings.hostname = request.form.get('hostname') or None
        settings.tls_enabled = request.form.get('tls_enabled') == 'true'
        settings.max_containers_per_user = int(request.form.get('max_containers_per_user', 1))
        settings.container_lifetime_minutes = int(request.form.get('container_lifetime_minutes', 15))
        settings.revert_cooldown_minutes = int(request.form.get('revert_cooldown_minutes', 5))
        settings.port_range_start = int(request.form.get('port_range_start', 30000))
        settings.port_range_end = int(request.form.get('port_range_end', 60000))
        settings.auto_cleanup_on_solve = request.form.get('auto_cleanup_on_solve') == 'true'
        settings.cleanup_stale_containers = request.form.get('cleanup_stale_containers') == 'true'
        settings.stale_container_hours = int(request.form.get('stale_container_hours', 2))
        settings.allowed_repositories = request.form.get('allowed_repositories', '').strip()
        
        # Handle certificate uploads
        if 'ca_cert' in request.files:
            ca_file = request.files['ca_cert']
            if ca_file and ca_file.filename:
                settings.ca_cert = ca_file.read().decode('utf-8')
        
        if 'client_cert' in request.files:
            cert_file = request.files['client_cert']
            if cert_file and cert_file.filename:
                settings.client_cert = cert_file.read().decode('utf-8')
        
        if 'client_key' in request.files:
            key_file = request.files['client_key']
            if key_file and key_file.filename:
                settings.client_key = key_file.read().decode('utf-8')
        
        # If TLS disabled, clear certificates
        if not settings.tls_enabled:
            settings.ca_cert = None
            settings.client_cert = None
            settings.client_key = None
        
        settings.save()
        
        # Reinitialize Docker client
        from services.container_manager import container_orchestrator
        container_orchestrator._init_docker_client()
        
        flash('Docker settings updated successfully', 'success')
        return redirect(url_for('admin.docker_settings'))
    
    return render_template('admin/docker_settings.html', docker_settings=settings)


@admin_bp.route('/docker/status')
@login_required
@admin_required
def docker_status():
    """View all active containers"""
    from models.container import ContainerInstance
    
    # Get all containers
    containers = ContainerInstance.objects(
        status__in=['starting', 'running']
    ).order_by('-started_at')
    
    # Enrich with user/team/challenge info
    container_data = []
    for c in containers:
        container_data.append({
            'id': str(c.id),
            'user': c.user.username if c.user else 'Unknown',
            'team': c.team.name if c.team else 'N/A',
            'challenge': c.challenge.name if c.challenge else 'Unknown',
            'container_id': c.container_id[:12] if c.container_id else 'N/A',
            'host_port': c.host_port,
            'status': c.status,
            'started_at': c.started_at,
            'expires_at': c.expires_at,
            'remaining_time': c.get_remaining_time() if c.expires_at else 'N/A'
        })
    
    return render_template('admin/docker_status.html', containers=container_data)


@admin_bp.route('/docker/containers/<string:container_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_container(container_id):
    """Admin force-delete a container"""
    from models.container import ContainerInstance
    from services.container_manager import container_orchestrator
    import docker
    
    try:
        container = ContainerInstance.objects.get_or_404(id=container_id)
        
        # Stop Docker container
        try:
            if container_orchestrator.docker_client:
                docker_container = container_orchestrator.docker_client.containers.get(container.container_id)
                docker_container.stop(timeout=10)
                docker_container.remove()
        except docker.errors.NotFound:
            pass  # Already removed
        except Exception as e:
            current_app.logger.error(f"Failed to stop container: {e}")
        
        # Update database
        container.status = 'stopped'
        container.stopped_at = datetime.utcnow()
        container.save()
        
        return jsonify({
            'success': True,
            'message': 'Container deleted successfully'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/docker/containers/delete-all', methods=['POST'])
@login_required
@admin_required
def delete_all_containers():
    """Delete all running containers"""
    from models.container import ContainerInstance
    from services.container_manager import container_orchestrator
    import docker
    
    try:
        containers = ContainerInstance.objects(
            status__in=['starting', 'running']
        )
        
        deleted_count = 0
        for container in containers:
            try:
                if container_orchestrator.docker_client:
                    docker_container = container_orchestrator.docker_client.containers.get(container.container_id)
                    docker_container.stop(timeout=10)
                    docker_container.remove()
            except docker.errors.NotFound:
                pass
            except Exception as e:
                current_app.logger.error(f"Failed to stop container {container.id}: {e}")
            
            container.status = 'stopped'
            container.stopped_at = datetime.utcnow()
            container.save()
            deleted_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Deleted {deleted_count} containers'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/docker/images')
@login_required
@admin_required
def list_docker_images():
    """List available Docker images"""
    from services.container_manager import container_orchestrator
    
    result = container_orchestrator.list_available_images()
    return jsonify(result)


@admin_bp.route('/dynamic-flags')
@login_required
@admin_required
def dynamic_flags_monitor():
    """Admin interface to monitor and verify dynamic flags for all active containers"""
    from models.container import ContainerInstance
    from services.cache import cache_service
    
    # Get all active containers (running or starting)
    active_containers = ContainerInstance.objects(
        status__in=['starting', 'running']
    ).order_by('-created_at')
    
    # Get all containers (including stopped) for verification history
    all_containers = ContainerInstance.objects.order_by('-created_at').limit(100)
    
    # Build detailed container info with flag data
    container_data = []
    for container in active_containers:
        # Get expected flag from multiple sources
        expected_flag = container.get_expected_flag()
        
        # Check cache mapping
        if container.team:
            team_part = f'team_{container.team.id}'
        else:
            team_part = f'user_{container.user.id}'
        
        mapping_key = f"dynamic_flag_mapping:{container.challenge.id}:{team_part}"
        cached_mapping = cache_service.get(mapping_key)
        
        # Check session cache
        session_cache = cache_service.get(f"dynamic_flag:{container.session_id}")
        
        # Parse flag to extract metadata
        flag_metadata = None
        if expected_flag:
            from services.container_manager import ContainerOrchestrator
            flag_metadata = ContainerOrchestrator.parse_dynamic_flag(expected_flag)
        
        container_data.append({
            'container': {
                'id': str(container.id),
                'session_id': container.session_id,
                'container_id': container.container_id,
                'docker_image': container.docker_image or '',
                'status': container.status,
                'created_at': container.created_at.isoformat() if container.created_at else None,
                'expires_at': container.expires_at.isoformat() if container.expires_at else None,
                'challenge_id': str(container.challenge.id) if container.challenge else None,
                'user_id': str(container.user.id) if container.user else None,
                'team_id': str(container.team.id) if container.team else None
            },
            'challenge_name': container.challenge.name if container.challenge else 'Unknown',
            'username': container.user.username if container.user else 'Unknown',
            'team_name': container.team.name if container.team else 'Solo',
            'expected_flag': expected_flag,
            'flag_in_db': container.dynamic_flag,
            'flag_in_cache_mapping': cached_mapping,
            'flag_in_session_cache': session_cache,
            'flag_metadata': flag_metadata,
            'flag_sources': {
                'db': bool(container.dynamic_flag),
                'mapping': bool(cached_mapping),
                'session': bool(session_cache)
            },
            'is_consistent': (
                container.dynamic_flag == expected_flag if expected_flag else True
            ),
            'remaining_time': container.get_remaining_time(),
            'is_expired': container.is_expired()
        })
    
    return render_template('admin/dynamic_flags.html', 
                         containers=container_data,
                         active_count=len(active_containers),
                         total_count=len(all_containers))


@admin_bp.route('/dynamic-flags/verify', methods=['POST'])
@login_required
@admin_required
def verify_dynamic_flag():
    """API endpoint to verify a submitted flag against a specific container"""
    from models.container import ContainerInstance
    
    data = request.get_json()
    container_id = data.get('container_id')
    submitted_flag = data.get('submitted_flag')
    
    if not container_id or not submitted_flag:
        return jsonify({
            'success': False,
            'error': 'container_id and submitted_flag are required'
        }), 400
    
    container = ContainerInstance.objects(id=container_id).first()
    if not container:
        return jsonify({
            'success': False,
            'error': 'Container not found'
        }), 404
    
    # Verify the flag
    verification = container.verify_flag(submitted_flag)
    
    return jsonify({
        'success': True,
        'verification': verification,
        'container': {
            'id': str(container.id),
            'challenge_name': container.challenge.name if container.challenge else 'Unknown',
            'team_name': container.team.name if container.team else 'Solo',
            'username': container.user.username if container.user else 'Unknown',
            'status': container.status,
            'is_expired': container.is_expired()
        }
    })


@admin_bp.route('/dynamic-flags/check-uniqueness', methods=['POST'])
@login_required
@admin_required
def check_flag_uniqueness():
    """Check if dynamic flags are unique across teams and detect any collisions"""
    from models.container import ContainerInstance
    from collections import defaultdict
    
    # Get all active containers with dynamic flags
    containers = ContainerInstance.objects(
        status__in=['starting', 'running'],
        dynamic_flag__ne=None
    )
    
    # Track flags by value to detect duplicates
    flag_registry = defaultdict(list)
    
    for container in containers:
        if container.dynamic_flag:
            flag_registry[container.dynamic_flag].append({
                'container_id': str(container.id),
                'challenge_id': str(container.challenge.id) if container.challenge else None,
                'challenge_name': container.challenge.name if container.challenge else 'Unknown',
                'team_id': str(container.team.id) if container.team else None,
                'team_name': container.team.name if container.team else 'Solo',
                'user_id': str(container.user.id) if container.user else None,
                'username': container.user.username if container.user else 'Unknown',
                'created_at': container.created_at.isoformat()
            })
    
    # Find duplicates (flags used by multiple containers)
    duplicates = {
        flag: instances 
        for flag, instances in flag_registry.items() 
        if len(instances) > 1
    }
    
    # Check for team collisions (same flag for different teams on same challenge)
    team_collisions = []
    for flag, instances in flag_registry.items():
        challenge_teams = defaultdict(list)
        for inst in instances:
            key = (inst['challenge_id'], inst['team_id'])
            challenge_teams[key].append(inst)
        
        # Check if same challenge has different teams with same flag
        challenge_groups = defaultdict(list)
        for (chal_id, team_id), insts in challenge_teams.items():
            challenge_groups[chal_id].append({'team_id': team_id, 'instances': insts})
        
        for chal_id, teams_data in challenge_groups.items():
            if len(teams_data) > 1:
                team_collisions.append({
                    'flag': flag,
                    'challenge_id': chal_id,
                    'teams': teams_data
                })
    
    return jsonify({
        'success': True,
        'total_active_containers': len(containers),
        'unique_flags': len(flag_registry),
        'duplicates_found': len(duplicates),
        'duplicates': duplicates,
        'team_collisions_found': len(team_collisions),
        'team_collisions': team_collisions,
        'is_robust': len(duplicates) == 0 and len(team_collisions) == 0
    })

