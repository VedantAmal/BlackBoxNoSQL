from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from models import db
from models.challenge import Challenge
from models.submission import Submission, Solve
from models.file import ChallengeFile
from models.user import User
from services.scoring import ScoringService
from services.cache import cache_service
from services.websocket import WebSocketService
from datetime import datetime
import re

challenges_bp = Blueprint('challenges', __name__, url_prefix='/challenges')


# Blueprint-level exception handler to ensure AJAX calls get JSON errors
@challenges_bp.errorhandler(Exception)
def _handle_challenges_exception(error):
    import traceback
    current_app.logger.error(f"Unhandled exception in challenges blueprint: {error}\n{traceback.format_exc()}")
    # Return JSON for AJAX/Fetch callers to avoid JSON.parse errors on HTML 500 pages
    return jsonify({'success': False, 'message': 'Internal server error'}), 500

@challenges_bp.route('/')
@login_required
def list_challenges():
    from models.settings import Settings
    
    # Check CTF status
    ctf_status = Settings.get_ctf_status()
    
    # Check if CTF has started (admins bypass this check)
    if not current_user.is_admin and ctf_status == 'not_started':
        start_time = Settings.get('ctf_start_time', type='datetime')
        return render_template('countdown.html', 
                             start_time=start_time,
                             page_title='Challenges',
                             return_url=url_for('challenges.list_challenges'))
    
    # If CTF is paused or ended, show status page instead of challenges
    if not current_user.is_admin and ctf_status in ('paused', 'ended'):
        return render_template('ctf_status.html', status=ctf_status)
    
    # Check if teams are enabled at all
    teams_enabled = Settings.get('teams_enabled', default=True, type='bool')
    
    # Check if team is required globally (only matters if teams are enabled)
    require_team = Settings.get('require_team_for_challenges', default=False, type='bool')
    team = current_user.get_team()
    
    # If teams are enabled AND team is required globally and user is not in a team (and not admin), show message
    if teams_enabled and require_team and not team and not current_user.is_admin:
        flash('You must join a team to view and solve challenges. Please join or create a team first.', 'warning')
        return redirect(url_for('teams.list_teams'))
    
    # Load all challenges that are either visible OR hidden but potentially unlockable
    # Note: solves relationship is lazy='dynamic', so we can't eager load it
    # We query both visible and hidden challenges, then filter by is_unlocked_for_user() later
    
    # Check if ACT system is enabled (optional feature)
    act_system_enabled = Settings.get('act_system_enabled', default=False, type='bool')
    
    try:
        from mongoengine.queryset.visitor import Q
        if act_system_enabled:
            # ACT system enabled - order by act, category, name
            challenges = Challenge.objects(
                Q(is_visible=True) | Q(is_hidden=True)
            ).order_by('act', 'category', 'name')
        else:
            # ACT system disabled - order by category, name only
            challenges = Challenge.objects(
                Q(is_visible=True) | Q(is_hidden=True)
            ).order_by('category', 'name')
    except Exception as e:
        # Fallback if ACT column doesn't exist or other error
        current_app.logger.warning(f"Error loading challenges with ACT system: {e}")
        act_system_enabled = False
        challenges = Challenge.objects(
            Q(is_visible=True) | Q(is_hidden=True)
        ).order_by('category', 'name')
    
    # Get unlocked ACTs for user/team (only if ACT system is enabled)
    unlocked_acts = []
    if act_system_enabled:
        try:
            from models.act_unlock import ActUnlock
            unlocked_acts = ActUnlock.get_unlocked_acts(
                user_id=current_user.id if not team else None,
                team_id=team.id if team else None
            )
        except Exception as e:
            # If ActUnlock doesn't work, disable ACT system
            current_app.logger.warning(f"Error loading ACT unlocks: {e}")
            act_system_enabled = False
            unlocked_acts = []
    
    # Batch check which challenges are solved (single query instead of N queries)
    # This is the key optimization - replaces N individual queries with 1 batch query
    challenge_ids = [c.id for c in challenges]
    if team:
        solved_ids = set(solve.challenge.id for solve in Solve.objects(
            team=team.id,
            challenge__in=challenge_ids
        ))
    else:
        solved_ids = set(solve.challenge.id for solve in Solve.objects(
            user=current_user.id,
            challenge__in=challenge_ids
        ))
    
    # Organize challenges by ACT, then by category within each ACT (or just by category if ACT system disabled)
    acts = {}
    for challenge in challenges:
        # Get ACT name (only if ACT system enabled)
        if act_system_enabled:
            act_name = getattr(challenge, 'act', None) or 'Uncategorized'
            
            # Check if ACT is unlocked (skip if not, unless admin)
            if not current_user.is_admin and act_name not in unlocked_acts:
                continue
        else:
            # ACT system disabled - use single category
            act_name = 'Challenges'
        
        # Check if challenge is enabled
        if not current_user.is_admin and not challenge.is_enabled:
            continue

        # Check if this specific challenge requires a team (only enforce if teams are enabled)
        if teams_enabled and challenge.requires_team and not team and not current_user.is_admin:
            continue  # Skip this challenge if it requires team and user has no team
        
        # Check if challenge is unlocked for user
        if not current_user.is_admin:
            if not challenge.is_unlocked_for_user(current_user.id, team.id if team else None):
                continue  # Skip hidden/locked challenges
        
        # Initialize ACT dict if needed
        if act_name not in acts:
            acts[act_name] = {}
        
        # Initialize category within ACT if needed
        if challenge.category not in acts[act_name]:
            acts[act_name][challenge.category] = []
        
        # Check if solved (using pre-loaded data)
        solved = challenge.id in solved_ids
        
        challenge_data = challenge.to_dict(include_flag=False)
        challenge_data['solved'] = solved
        challenge_data['requires_team'] = challenge.requires_team
        
        # Add prerequisite info if locked
        if challenge.unlock_mode == 'prerequisite':
            missing = challenge.get_missing_prerequisites(current_user.id, team.id if team else None)
            if missing:
                challenge_data['locked'] = True
                challenge_data['missing_prerequisites'] = [c.name for c in missing]
        
        acts[act_name][challenge.category].append(challenge_data)
    
    return render_template('challenges.html', 
                          acts=acts, 
                          unlocked_acts=unlocked_acts, 
                          team=team,
                          act_system_enabled=act_system_enabled)


@challenges_bp.route('/<string:challenge_id>')
@login_required
def view_challenge(challenge_id):
    """View challenge details"""
    from models.settings import Settings
    
    challenge = Challenge.objects(id=challenge_id).first_or_404()
    
    # Get user's team first (needed for unlock checks)
    team = current_user.get_team()
    team_id = team.id if team else None
    
    # Check if challenge is enabled
    if not current_user.is_admin and not challenge.is_enabled:
        flash('Challenge not found', 'error')
        return redirect(url_for('challenges.list_challenges'))

    # Check if challenge is unlocked for this specific user/team
    # This handles both visible challenges and hidden/prerequisite/flag-unlocked challenges
    if not current_user.is_admin:
        if not challenge.is_unlocked_for_user(current_user.id, team_id):
            flash('Challenge not found', 'error')
            return redirect(url_for('challenges.list_challenges'))
    
    # Check if teams are enabled
    teams_enabled = Settings.get('teams_enabled', default=True, type='bool')
    
    # Check if team is required (either globally or per-challenge) - only if teams are enabled
    require_team_global = Settings.get('require_team_for_challenges', default=False, type='bool')
    
    if teams_enabled and (require_team_global or challenge.requires_team) and not team and not current_user.is_admin:
        flash('You must be in a team to view this challenge. Please join or create a team first.', 'warning')
        return redirect(url_for('teams.list_teams'))
    
    # Check if solved
    if team:
        solved = challenge.is_solved_by_team(team.id)
    else:
        solved = challenge.is_solved_by_user(current_user.id)
    
    challenge_data = challenge.to_dict(include_flag=False)
    challenge_data['solved'] = solved
    challenge_data['requires_team'] = challenge.requires_team
    
    # Get challenge files and images
    challenge_files = ChallengeFile.objects(challenge=challenge_id, is_image=False)
    files_data = [f.to_dict() for f in challenge_files]
    
    challenge_images = ChallengeFile.objects(challenge=challenge_id, is_image=True)
    images_data = [{'url': img.get_download_url(), 'original_filename': img.original_filename, 'id': str(img.id)} for img in challenge_images]
    
    # Get hints
    from models.hint import Hint
    hints = Hint.objects(challenge=challenge_id).order_by('order')
    hints_data = []
    for hint in hints:
        # Check if unlocked
        if team:
            unlocked = hint.is_unlocked_by_team(team.id)
        else:
            unlocked = hint.is_unlocked_by_user(current_user.id)
        
        hint_info = {
            'id': str(hint.id),
            'cost': hint.cost,
            'order': hint.order,
            'unlocked': unlocked,
        }
        
        if unlocked or current_user.is_admin:
            hint_info['content'] = hint.content
        
        hints_data.append(hint_info)
    
    # Check if challenge has branching (multiple paths)
    from models.branching import ChallengeFlag, ChallengeUnlock
    challenge_flags = ChallengeFlag.objects(challenge=challenge_id)
    has_branching = any(flag.unlocks_challenge is not None for flag in challenge_flags)
    challenge_data['has_branching'] = has_branching
    
    # Get unlocked paths for this user/team
    unlocked_paths = []
    if solved and has_branching:
        user_id = current_user.id
        team_id = team.id if team else None
        
        # Find all flags from THIS challenge that unlock other challenges
        unlocking_flags = ChallengeFlag.objects(
            challenge=challenge_id,
            unlocks_challenge__ne=None
        )
        
        # For each unlocking flag, check if user has unlocked it
        for flag in unlocking_flags:
            from mongoengine.queryset.visitor import Q
            unlock_query = ChallengeUnlock.objects(
                unlocked_by_flag=flag.id
            )
            
            if team_id:
                unlock_query = unlock_query.filter(
                    Q(user=user_id) | Q(team=team_id)
                )
            else:
                unlock_query = unlock_query.filter(user=user_id)
                
            unlock = unlock_query.first()
            
            if unlock:
                unlocked_challenge = Challenge.objects(id=flag.unlocks_challenge.id).first()
                if unlocked_challenge:
                    unlocked_paths.append({
                        'challenge_name': unlocked_challenge.name,
                        'category': unlocked_challenge.category,
                        'flag_label': flag.flag_label if flag.flag_label else 'primary flag'
                    })
    
    challenge_data['unlocked_paths'] = unlocked_paths
    
    # Get list of solvers (users/teams who solved this challenge)
    solvers = []
    from models.settings import Settings
    teams_enabled = Settings.get('teams_enabled', True)
    team_mode = Settings.get('team_mode', False)
    
    if team_mode:
        # Team mode: show teams that solved
        team_solves = Solve.objects(
            challenge=challenge_id,
            team__ne=None
        ).order_by('solved_at')
        
        seen_teams = set()
        for solve in team_solves:
            if solve.team and solve.team.id not in seen_teams:
                seen_teams.add(solve.team.id)
                from models.team import Team
                team_obj = Team.objects(id=solve.team.id).first()
                if team_obj:
                    solvers.append({
                        'name': team_obj.name,
                        'is_team': True,
                        'solved_at': solve.solved_at
                    })
    else:
        # Solo mode: show users that solved
        user_solves = Solve.objects(
            challenge=challenge_id,
            user__ne=None
        ).order_by('solved_at')
        
        seen_users = set()
        for solve in user_solves:
            if solve.user and solve.user.id not in seen_users:
                seen_users.add(solve.user.id)
                user_obj = User.objects(id=solve.user.id).first()
                if user_obj:
                    solvers.append({
                        'name': user_obj.username,
                        'is_team': False,
                        'solved_at': solve.solved_at
                    })
    
    challenge_data['solvers'] = solvers
    challenge_data['solver_count'] = len(solvers)
    
    return render_template('challenge_detail.html', 
                          challenge=challenge_data, 
                          files=files_data,
                          images=images_data,
                          hints=hints_data,
                          team=team)


@challenges_bp.route('/<string:challenge_id>/submit', methods=['POST'])
@login_required
def submit_flag(challenge_id):
    """Submit a flag for a challenge"""
    from models.settings import Settings
    
    # Check CTF status
    ctf_status = Settings.get_ctf_status()
    
    if ctf_status == 'not_started':
        start_time = Settings.get('ctf_start_time')
        return jsonify({
            'success': False, 
            'message': f'CTF has not started yet. Starts at: {start_time.strftime("%Y-%m-%d %H:%M UTC") if start_time else "TBD"}'
        }), 403
    
    if ctf_status == 'ended':
        end_time = Settings.get('ctf_end_time')
        return jsonify({
            'success': False, 
            'message': f'CTF has ended. Ended at: {end_time.strftime("%Y-%m-%d %H:%M UTC") if end_time else "Unknown"}'
        }), 403
    
    if ctf_status == 'paused':
        return jsonify({
            'success': False, 
            'message': 'CTF is currently paused by administrators. Please wait for it to resume.'
        }), 403
    
    challenge = Challenge.objects.get_or_404(id=challenge_id)
    
    # Get user's team first (needed for unlock checks)
    team = current_user.team
    team_id = team.id if team else None
    
    # Check if challenge is unlocked for this specific user/team
    if not current_user.is_admin:
        if not challenge.is_unlocked_for_user(current_user.id, team_id):
            return jsonify({'success': False, 'message': 'Challenge not found'}), 404
    
    # Check if challenge is enabled
    if not challenge.is_enabled and not current_user.is_admin:
        return jsonify({
            'success': False, 
            'message': 'This challenge is temporarily disabled. Please try again later.'
        }), 403
    
    # Check if teams are enabled
    teams_enabled = Settings.get('teams_enabled', default=True, type='bool')
    
    # Check if team is required for this challenge (only if teams are enabled)
    if teams_enabled and challenge.requires_team and not team_id and not current_user.is_admin:
        return jsonify({
            'success': False, 
            'message': 'You must be in a team to solve this challenge. Please join or create a team first.'
        }), 403
    
    # Check global team requirement setting (only if teams are enabled)
    if teams_enabled and Settings.get('require_team_for_challenges', default=False, type='bool') and not team_id and not current_user.is_admin:
        return jsonify({
            'success': False, 
            'message': 'You must be in a team to solve challenges. Please join or create a team first.'
        }), 403
    
    submitted_flag = request.form.get('flag', '').strip()
    
    if not submitted_flag:
        return jsonify({'success': False, 'message': 'Please enter a flag'}), 400
    
    # Check if already solved (by user or team)
    if team:
        already_solved = challenge.is_solved_by_team(team_id)
    else:
        already_solved = challenge.is_solved_by_user(current_user.id)
    
    # Check if this challenge has branching flags (allows re-submission for different paths)
    from models.branching import ChallengeFlag
    challenge_flags = ChallengeFlag.objects(challenge=challenge)
    has_branching = any(flag.unlocks_challenge is not None for flag in challenge_flags)
    
    # If already solved and challenge has no branching, reject submission
    if already_solved and not has_branching:
        return jsonify({'success': False, 'message': 'This challenge has already been solved'}), 400
    
    # Check max attempts limit (0 means unlimited)
    if challenge.max_attempts and challenge.max_attempts > 0:
        if team_id:
            # Count team's attempts for this challenge
            team_attempts = Submission.objects(
                challenge=challenge,
                team=team
            ).count()
            
            if team_attempts >= challenge.max_attempts:
                return jsonify({
                    'success': False,
                    'message': f'Maximum attempts ({challenge.max_attempts}) reached for this challenge'
                }), 400
        else:
            # Count user's attempts
            user_attempts = Submission.objects(
                challenge=challenge,
                user=current_user
            ).count()
            
            if user_attempts >= challenge.max_attempts:
                return jsonify({
                    'success': False,
                    'message': f'Maximum attempts ({challenge.max_attempts}) reached for this challenge'
                }), 400
    
    # Rate limiting check (prevent brute force)
    rate_limit_key = f'submissions:{current_user.id}:{challenge_id}'
    is_allowed, remaining = cache_service.check_rate_limit(rate_limit_key, limit=10, window=60)
    
    if not is_allowed:
        return jsonify({
            'success': False,
            'message': 'Too many attempts. Please wait before trying again.'
        }), 429
    
    # Check the flag
    matched_flag = challenge.check_flag(submitted_flag, team_id=team_id, user_id=current_user.id)
    is_correct = matched_flag is not None
    
    # ANTI-FLAG-SHARING: Check if submitted flag is a dynamic flag from another team
    if not is_correct and challenge.docker_enabled:
        from services.container_manager import ContainerOrchestrator
        from models.flag_abuse import FlagAbuseAttempt
        from models.container import ContainerInstance
        
        parsed_flag = ContainerOrchestrator.parse_dynamic_flag(submitted_flag)
        if parsed_flag and parsed_flag.get('is_valid'):
            # This is a valid dynamic flag format
            flag_challenge_id = parsed_flag.get('challenge_id')
            flag_team_id = parsed_flag.get('team_id')
            flag_instance_id = parsed_flag.get('user_id')  # This is user_id for user flags
            
            # Check if this flag belongs to a different team/user
            is_wrong_team = False
            actual_owner_team_id = None
            actual_owner_user_id = None
            
            if flag_challenge_id == str(challenge_id):
                # Flag is for this challenge
                if parsed_flag.get('is_team_flag') and flag_team_id:
                    # It's a team flag - check if it's a different team
                    if team_id and flag_team_id != str(team_id):
                        is_wrong_team = True
                        actual_owner_team_id = flag_team_id
                    elif not team_id and flag_team_id:
                        # User not in team trying to use team's flag
                        is_wrong_team = True
                        actual_owner_team_id = flag_team_id
                elif not parsed_flag.get('is_team_flag') and flag_instance_id:
                    # It's a user flag (no team) - the flag contains user_id
                    flag_user_id = flag_instance_id
                    
                    # Check if the flag belongs to the current user
                    if flag_user_id == str(current_user.id):
                        # Verify the flag against the active container for this user/challenge
                        # or check the cache mapping
                        mapping_key = f"dynamic_flag_mapping:{challenge_id}:user_{flag_user_id}"
                        mapping_flag = cache_service.get(mapping_key)
                        
                        # Also check active container if available (more reliable if cache expired but container running)
                        instance = ContainerInstance.objects(
                            user=current_user, 
                            challenge=challenge,
                            status='running'
                        ).first()
                        
                        instance_flag = getattr(instance, 'dynamic_flag', None) if instance else None
                        expected_flag = instance_flag or mapping_flag
                        
                        if expected_flag and submitted_flag == expected_flag:
                            is_correct = True
                            # Return a lightweight dynamic flag match object so downstream logic
                            # (award points, create submission) works the same as Challenge.check_flag
                            case_sens = getattr(challenge, 'flag_case_sensitive', True)

                            class _DynamicFlagMatch:
                                def __init__(self, value, case_sensitive):
                                    self.id = None
                                    self.is_regex = False
                                    self.is_case_sensitive = case_sensitive
                                    self.flag_value = value
                                    self.points_override = None
                                    self.unlocks_challenge = None
                                    self.flag_label = None

                            matched_flag = _DynamicFlagMatch(submitted_flag, case_sens)
                        else:
                            # Flag format is valid but content doesn't match expected flag for this user
                            pass
                    else:
                        # Flag belongs to another user
                        is_wrong_team = True
                        actual_owner_user_id = flag_user_id
            
            # Log the flag sharing attempt
            if is_wrong_team:
                # Validate that referenced entities exist (to avoid FK constraint errors)
                from models.team import Team
                from models.user import User
                
                if actual_owner_team_id:
                    team_exists = Team.objects(id=actual_owner_team_id).first() is not None
                    if not team_exists:
                        actual_owner_team_id = None  # Team was deleted, set to NULL
                
                if actual_owner_user_id:
                    user_exists = User.objects(id=actual_owner_user_id).first() is not None
                    if not user_exists:
                        actual_owner_user_id = None  # User was deleted, set to NULL
                
                # Analyze temporal patterns to determine severity
                pattern_analysis = FlagAbuseAttempt.analyze_temporal_patterns(
                    challenge_id=challenge_id,
                    submitting_team_id=team_id,
                    actual_team_id=actual_owner_team_id,
                    time_window_minutes=15
                )
                
                # Determine severity based on pattern analysis
                severity = pattern_analysis.get('severity', 'warning')
                pattern_notes = pattern_analysis.get('notes', '')
                
                # Resolve owner name for nicer notes/logs
                owner_label = None
                try:
                    if actual_owner_team_id:
                        owner = Team.objects(id=actual_owner_team_id).first()
                        owner_label = f"team {owner.name}" if owner else f"team {actual_owner_team_id}"
                    elif actual_owner_user_id:
                        owner = User.objects(id=actual_owner_user_id).first()
                        owner_label = f"user {owner.username}" if owner else f"user {actual_owner_user_id}"
                    else:
                        owner_label = "deleted user/team"
                except Exception:
                    owner_label = f"team {actual_owner_team_id}" if actual_owner_team_id else f"user {actual_owner_user_id or 'unknown'}"
                
                # Build comprehensive notes
                base_note = f'Attempted to submit flag belonging to {owner_label}'
                if pattern_notes:
                    full_notes = f"{base_note}. {pattern_notes}"
                else:
                    full_notes = base_note

                abuse_record = FlagAbuseAttempt(
                    user=current_user,
                    team=team,
                    challenge=challenge,
                    submitted_flag=submitted_flag,
                    actual_team_id=actual_owner_team_id,
                    actual_user_id=actual_owner_user_id,
                    ip_address=request.remote_addr,
                    severity=severity,
                    notes=full_notes
                )
                abuse_record.save()
                
                # Log with appropriate severity level
                if severity == 'critical':
                    current_app.logger.error(
                        f"FLAG SHARING - CRITICAL PATTERN: User {current_user.id} (team {team_id}) "
                        f"submitted flag for challenge {challenge_id} belonging to {owner_label}. {pattern_notes}"
                    )
                elif severity == 'suspicious':
                    current_app.logger.warning(
                        f"FLAG SHARING - SUSPICIOUS: User {current_user.id} (team {team_id}) "
                        f"submitted flag for challenge {challenge_id} belonging to {owner_label}. {pattern_notes}"
                    )
                else:
                    current_app.logger.warning(
                        f"FLAG SHARING ATTEMPT: User {current_user.id} (team {team_id}) "
                        f"submitted flag for challenge {challenge_id} that belongs to {owner_label}"
                    )
    
    # Create submission record
    submission = Submission(
        user=current_user,
        challenge=challenge,
        team=team,
        submitted_flag=submitted_flag,
        is_correct=is_correct,
        ip_address=request.remote_addr
    )
    submission.save()
    
    if is_correct:
        # DETECT exact regex-based flag sharing (admin-controlled per-challenge)
        try:
            from models.flag_abuse import FlagAbuseAttempt
            from datetime import timedelta, datetime

            # Only consider when this flag was matched via a regex flag and the challenge has monitoring enabled
            if hasattr(matched_flag, 'is_regex') and matched_flag.is_regex and getattr(challenge, 'detect_regex_sharing', False):
                # Time window (minutes) to consider prior identical submissions. Configurable via app config.
                window_minutes = int(current_app.config.get('REGEX_SHARING_WINDOW_MINUTES', 60))
                cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)

                # Find a prior correct submission of the exact same submitted_flag by another team/user within the window
                prior_query = Submission.objects(
                    challenge=challenge,
                    submitted_flag=submitted_flag,
                    is_correct=True,
                    submitted_at__gte=cutoff
                )

                # Exclude current team/user
                if team_id:
                    prior_query = prior_query.filter(team__ne=None).filter(team__ne=team)
                else:
                    prior_query = prior_query.filter(user__ne=None).filter(user__ne=current_user)

                prior = prior_query.order_by('submitted_at').first()

                if prior:
                    actual_owner_team_id = str(prior.team.id) if prior.team else None
                    actual_owner_user_id = str(prior.user.id) if prior.user else None

                    # Validate that referenced entities exist (to avoid FK constraint errors)
                    from models.team import Team
                    from models.user import User
                    
                    if actual_owner_team_id:
                        team_exists = Team.objects(id=actual_owner_team_id).first() is not None
                        if not team_exists:
                            actual_owner_team_id = None
                    
                    if actual_owner_user_id:
                        user_exists = User.objects(id=actual_owner_user_id).first() is not None
                        if not user_exists:
                            actual_owner_user_id = None

                    # Resolve owner label (team name or username) for nicer notes/logs
                    owner_label = None
                    try:
                        if actual_owner_team_id:
                            owner = Team.objects(id=actual_owner_team_id).first()
                            owner_label = f"team {owner.name}" if owner and owner.name else f"team {actual_owner_team_id}"
                        elif actual_owner_user_id:
                            owner = User.objects(id=actual_owner_user_id).first()
                            owner_label = f"user {owner.username}" if owner and owner.username else f"user {actual_owner_user_id}"
                        else:
                            owner_label = "deleted user/team"
                    except Exception:
                        owner_label = f"team {actual_owner_team_id}" if actual_owner_team_id else f"user {actual_owner_user_id or 'unknown'}"

                    # Record a FlagAbuseAttempt for this exact-match regex sharing
                    notes = f'Exact regex-derived flag "{submitted_flag}" previously submitted by {owner_label} at {prior.submitted_at.isoformat()}'

                    abuse_record = FlagAbuseAttempt(
                        user=current_user,
                        team=team,
                        challenge=challenge,
                        submitted_flag=submitted_flag,
                        actual_team_id=actual_owner_team_id,
                        actual_user_id=actual_owner_user_id,
                        ip_address=request.remote_addr,
                        severity='suspicious',
                        notes=notes
                    )
                    abuse_record.save()
                    current_app.logger.warning(f"Regex-sharing detected: {notes}")
                else:
                    # If no exact-match prior submission was found, also check for prior
                    # submissions that match the same regex pattern (different concrete strings).
                    try:
                        flags_pattern = None
                        if matched_flag.is_case_sensitive:
                            flags_pattern = re.compile(matched_flag.flag_value)
                        else:
                            flags_pattern = re.compile(matched_flag.flag_value, re.IGNORECASE)

                        broader_query = Submission.objects(
                            challenge=challenge,
                            is_correct=True,
                            submitted_at__gte=cutoff
                        )

                        # Exclude current team/user
                        if team_id:
                            broader_query = broader_query.filter(team__ne=None).filter(team__ne=team)
                        else:
                            broader_query = broader_query.filter(user__ne=None).filter(user__ne=current_user)

                        # Iterate prior correct submissions and check whether their submitted_flag
                        # would also match the same regex pattern. This detects when different
                        # users submitted different concrete values that both match the same regex.
                        for prior_row in broader_query.order_by('submitted_at').limit(50):
                            try:
                                if flags_pattern.fullmatch(prior_row.submitted_flag or ''):
                                    actual_owner_team_id = str(prior_row.team.id) if prior_row.team else None
                                    actual_owner_user_id = str(prior_row.user.id) if prior_row.user else None

                                    # Validate that referenced entities exist (to avoid FK constraint errors)
                                    from models.team import Team
                                    from models.user import User
                                    
                                    if actual_owner_team_id:
                                        team_exists = Team.objects(id=actual_owner_team_id).first() is not None
                                        if not team_exists:
                                            actual_owner_team_id = None
                                    
                                    if actual_owner_user_id:
                                        user_exists = User.objects(id=actual_owner_user_id).first() is not None
                                        if not user_exists:
                                            actual_owner_user_id = None

                                    # Resolve owner label (team name or username) for nicer notes/logs
                                    owner_label = None
                                    try:
                                        if actual_owner_team_id:
                                            owner = Team.objects(id=actual_owner_team_id).first()
                                            owner_label = f"team {owner.name}" if owner and owner.name else f"team {actual_owner_team_id}"
                                        elif actual_owner_user_id:
                                            owner = User.objects(id=actual_owner_user_id).first()
                                            owner_label = f"user {owner.username}" if owner and owner.username else f"user {actual_owner_user_id}"
                                        else:
                                            owner_label = "deleted user/team"
                                    except Exception:
                                        owner_label = f"team {actual_owner_team_id}" if actual_owner_team_id else f"user {actual_owner_user_id or 'unknown'}"

                                    notes = (
                                        f'Regex-derived flag pattern "{matched_flag.flag_value}" matched prior submission "{prior_row.submitted_flag}" '
                                        f'by {owner_label} at {prior_row.submitted_at.isoformat()}'
                                    )

                                    abuse_record = FlagAbuseAttempt(
                                        user=current_user,
                                        team=team,
                                        challenge=challenge,
                                        submitted_flag=submitted_flag,
                                        actual_team_id=actual_owner_team_id,
                                        actual_user_id=actual_owner_user_id,
                                        ip_address=request.remote_addr,
                                        severity='suspicious',
                                        notes=notes
                                    )
                                    abuse_record.save()
                                    current_app.logger.warning(f"Regex-sharing (pattern match) detected: {notes}")
                                    break
                            except Exception:
                                # ignore per-row match errors and continue
                                continue
                    except re.error:
                        # Invalid regex - nothing to do here (should be validated earlier)
                        pass
        except Exception as e:
            current_app.logger.debug(f"Regex-sharing detection error: {e}")
        # Calculate points at time of solve
        points = challenge.get_current_points()
        
        # Check if flag has a points override
        if hasattr(matched_flag, 'points_override') and matched_flag.points_override:
            points = matched_flag.points_override
        
        # Check if this is first blood (first solve of this challenge)
        from models.settings import Settings
        is_first_blood = False
        first_blood_bonus = Settings.get('first_blood_bonus', 0, type='int')
        
        # LOCKING: Lock the challenge row to prevent race conditions on first blood
        # This ensures that if multiple users submit simultaneously, they are processed sequentially
        # for the purpose of determining first blood.
        # MongoDB doesn't support row locking like SQL. We rely on atomic operations where possible.
        # Challenge.objects(id=challenge_id).first()
        
        existing_solves = Solve.objects(challenge=challenge).count()
        
        if existing_solves == 0:
            is_first_blood = True
            if first_blood_bonus > 0:
                points += first_blood_bonus
        
        # Create solve record - marks challenge as solved for entire team
        solve = Solve(
            user=current_user,
            challenge=challenge,
            flag=matched_flag.id if hasattr(matched_flag, 'id') else None,
            team=team,
            points_earned=points,
            is_first_blood=is_first_blood
        )
        solve.save()
        
        # Auto-stop container if challenge has one (cleanup after solve)
        if challenge.docker_enabled:
            try:
                from services.container_manager import container_orchestrator
                stop_result = container_orchestrator.stop_container(str(challenge.id), str(current_user.id), force=True)
                if stop_result.get('success'):
                    current_app.logger.info(f"Auto-stopped container for solved challenge {challenge.id} by user {current_user.id}")
                else:
                    current_app.logger.warning(f"Failed to auto-stop container for solved challenge {challenge.id}: {stop_result.get('error', 'Unknown error')}")
            except Exception as e:
                current_app.logger.error(f"Error auto-stopping container for solved challenge {challenge.id}: {e}")
        
        # Handle challenge unlocking via flags and prerequisites
        from models.branching import ChallengeUnlock, ChallengePrerequisite
        unlocked_challenges = []
        unlocked_act = None
        
        # Handle ACT unlocking if this challenge unlocks a new ACT (only if ACT system enabled)
        act_system_enabled = Settings.get('act_system_enabled', default=False, type='bool')
        if act_system_enabled and challenge.unlocks_act:
            from models.act_unlock import ActUnlock
            act_unlocked = ActUnlock.unlock_act(
                act=challenge.unlocks_act,
                user_id=current_user.id if not team_id else None,
                team_id=team_id,
                challenge_id=challenge_id
            )
            if act_unlocked:
                unlocked_act = challenge.unlocks_act
                current_app.logger.info(
                    f"ACT {challenge.unlocks_act} unlocked for "
                    f"{'team ' + str(team_id) if team_id else 'user ' + str(current_user.id)} "
                    f"by solving challenge {challenge_id} ({challenge.name})"
                )
        
        # Check if solving this challenge unlocks any prerequisite-gated challenges
        prerequisite_dependents = ChallengePrerequisite.objects(
            prerequisite_challenge=challenge
        )
        
        for dependent in prerequisite_dependents:
            dependent_challenge = dependent.challenge
            
            # Check if all prerequisites are now met for this dependent challenge
            if dependent_challenge.unlock_mode == 'prerequisite':
                # Use the model's method to check if now unlocked
                if dependent_challenge.is_unlocked_for_user(current_user.id, team_id):
                    unlocked_challenges.append({
                        'id': str(dependent_challenge.id),
                        'name': dependent_challenge.name,
                        'category': dependent_challenge.category
                    })
                    current_app.logger.info(
                        f"Challenge {dependent_challenge.id} ({dependent_challenge.name}) now visible for "
                        f"{'team ' + str(team_id) if team_id else 'user ' + str(current_user.id)} "
                        f"after completing prerequisite {challenge_id} ({challenge.name})"
                    )
        
        if hasattr(matched_flag, 'unlocks_challenge') and matched_flag.unlocks_challenge:
            # Check if this specific path/challenge was already unlocked by this user/team
            from mongoengine.queryset.visitor import Q
            unlock_query = ChallengeUnlock.objects(
                challenge=matched_flag.unlocks_challenge
            )
            
            if team_id:
                unlock_query = unlock_query.filter(
                    Q(user=current_user.id) | Q(team=team_id)
                )
            else:
                unlock_query = unlock_query.filter(user=current_user.id)
                
            existing_unlock = unlock_query.first()
            
            if existing_unlock:
                # Path already unlocked, inform user but don't create duplicate
                unlocked_challenge = matched_flag.unlocks_challenge
                return jsonify({
                    'success': False,
                    'message': f'You have already unlocked the path to "{unlocked_challenge.name if unlocked_challenge else "this challenge"}" with a different flag.'
                }), 400
            
            # This flag unlocks another challenge - create unlock record (per-user/team)
            # Create unlock record. The DB requires a non-null user_id, so
            # always store the current user as the actor. We also include
            # team_id when this is a team-based unlock so it can be treated
            # as a team-wide unlock semantically (team_id != None).
            unlock_record = ChallengeUnlock(
                user=current_user,
                team=team,
                challenge=matched_flag.unlocks_challenge,
                unlocked_by_flag=matched_flag
            )
            unlock_record.save()
            
            # Get the unlocked challenge details
            unlocked_challenge = matched_flag.unlocks_challenge
            if unlocked_challenge:
                # Do NOT modify is_hidden/is_visible - challenge stays hidden globally
                # Visibility is controlled per-user/team via ChallengeUnlock + is_unlocked_for_user()
                unlocked_challenges.append({
                    'id': str(unlocked_challenge.id),
                    'name': unlocked_challenge.name,
                    'category': unlocked_challenge.category
                })
                current_app.logger.info(
                    f"Challenge {unlocked_challenge.id} ({unlocked_challenge.name}) unlocked for "
                    f"{'team ' + str(team_id) if team_id else 'user ' + str(current_user.id)} "
                    f"via flag {matched_flag.id}"
                )
        
        # Scores are automatically calculated from Solve records
        # No need to update user.score or team.score (they don't exist as columns)
        
        # Invalidate caches
        cache_service.invalidate_scoreboard()
        cache_service.invalidate_challenge(challenge_id)
        if team_id:
            cache_service.invalidate_team(team_id)
        else:
            cache_service.invalidate_user(current_user.id)
        
        # Emit WebSocket events for live updates
        solve_data = {
            'user': current_user.username,
            'team': team.name if team else None,
            'challenge': challenge.name,
            'category': challenge.category,
            'points': points,
            'timestamp': datetime.utcnow().isoformat()
        }
        WebSocketService.emit_new_solve(solve_data)
        
        # Update challenge points (may have changed)
        new_points = challenge.get_current_points()
        if new_points != points:
            WebSocketService.emit_challenge_update({
                'id': str(challenge.id),
                'name': challenge.name,
                'points': new_points
            })
        
        # Send updated scoreboard (check if teams are enabled)
        teams_enabled = Settings.get('teams_enabled', default=True, type='bool')
        cache_key = 'scoreboard_team' if teams_enabled else 'scoreboard_individual'
        scoreboard = ScoringService.get_scoreboard(team_based=teams_enabled, limit=50)
        cache_service.set(cache_key, scoreboard, ttl=60)
        WebSocketService.emit_scoreboard_update(scoreboard)
        
        message = 'Correct flag! Challenge solved!'
        if team:
            message += f' Points awarded to team "{team.name}".'
        
        # Add info about unlocked challenges
        response_data = {
            'success': True,
            'message': message,
            'points': points
        }
        
        # Add ACT unlock notification
        if unlocked_act:
            response_data['unlocked_act'] = unlocked_act
            response_data['message'] += f'{unlocked_act} has been unlocked!'
        
        if unlocked_challenges:
            unlocked_names = ', '.join([c['name'] for c in unlocked_challenges])
            response_data['unlocked_challenges'] = unlocked_challenges
            response_data['message'] += f' New challenge(s) unlocked: {unlocked_names}!'
        
        return jsonify(response_data)
    else:
        # Calculate remaining attempts if limited
        attempts_remaining = None
        if challenge.max_attempts and challenge.max_attempts > 0:
            if team_id:
                attempts_used = Submission.objects(
                    challenge=challenge,
                    team=team
                ).count()
            else:
                attempts_used = Submission.objects(
                    challenge=challenge,
                    user=current_user
                ).count()
            attempts_remaining = challenge.max_attempts - attempts_used
        
        response = {
            'success': False,
            'message': 'Incorrect flag'
        }
        
        if attempts_remaining is not None:
            response['attempts_remaining'] = attempts_remaining
            if attempts_remaining > 0:
                response['message'] += f' ({attempts_remaining} attempts remaining)'
        
        return jsonify(response), 400


@challenges_bp.route('/<string:challenge_id>/explore', methods=['POST'])
@login_required
def explore_flag(challenge_id):
    """Submit an additional flag for an already-solved challenge to unlock more paths (no points awarded)"""
    from models.settings import Settings
    from models.branching import ChallengeFlag, ChallengeUnlock
    
    # Check CTF status
    ctf_status = Settings.get_ctf_status()
    
    if ctf_status == 'not_started':
        start_time = Settings.get('ctf_start_time')
        return jsonify({
            'success': False, 
            'message': f'CTF has not started yet. Starts at: {start_time.strftime("%Y-%m-%d %H:%M UTC") if start_time else "TBD"}'
        }), 403
    
    if ctf_status == 'ended':
        end_time = Settings.get('ctf_end_time')
        return jsonify({
            'success': False, 
            'message': f'CTF has ended. Ended at: {end_time.strftime("%Y-%m-%d %H:%M UTC") if end_time else "Unknown"}'
        }), 403
    
    if ctf_status == 'paused':
        return jsonify({
            'success': False, 
            'message': 'CTF is currently paused by administrators. Please wait for it to resume.'
        }), 403
    
    challenge = Challenge.objects.get_or_404(id=challenge_id)
    # Get user's team (needed for unlock checks)
    team = current_user.team
    team_id = team.id if team else None

    # Only allow access if challenge is unlocked for this user/team or user is admin
    if not current_user.is_admin:
        if not challenge.is_unlocked_for_user(current_user.id, team_id):
            return jsonify({'success': False, 'message': 'Challenge not found'}), 404
    
    # Check if already solved (must be solved to explore)
    if team:
        already_solved = challenge.is_solved_by_team(team_id)
    else:
        already_solved = challenge.is_solved_by_user(current_user.id)
    
    if not already_solved:
        return jsonify({
            'success': False, 
            'message': 'You must solve this challenge first before exploring additional paths'
        }), 403
    
    # Check if this challenge has branching flags
    challenge_flags = ChallengeFlag.objects(challenge=challenge)
    has_branching = any(flag.unlocks_challenge is not None for flag in challenge_flags)
    
    if not has_branching:
        return jsonify({
            'success': False, 
            'message': 'This challenge has no additional paths to explore'
        }), 400
    
    submitted_flag = request.form.get('flag', '').strip()
    
    if not submitted_flag:
        return jsonify({'success': False, 'message': 'Please enter a flag'}), 400
    
    # Rate limiting check (prevent brute force)
    rate_limit_key = f'explore:{current_user.id}:{challenge_id}'
    is_allowed, remaining = cache_service.check_rate_limit(rate_limit_key, limit=10, window=60)
    
    if not is_allowed:
        return jsonify({
            'success': False,
            'message': 'Too many attempts. Please wait before trying again.'
        }), 429
    
    # Check the flag
    matched_flag = challenge.check_flag(submitted_flag, team_id=team_id, user_id=current_user.id)
    
    if not matched_flag:
        return jsonify({'success': False, 'message': 'Incorrect flag'}), 400
    
    # Check if this specific flag unlocks anything
    if not hasattr(matched_flag, 'unlocks_challenge') or not matched_flag.unlocks_challenge:
        return jsonify({
            'success': False, 
            'message': 'This flag does not unlock any additional paths'
        }), 400
    
    # Check if this path was already unlocked
    from mongoengine.queryset.visitor import Q
    unlock_query = ChallengeUnlock.objects(
        unlocked_by_flag=matched_flag
    )
    
    if team_id:
        unlock_query = unlock_query.filter(
            Q(user=current_user.id) | Q(team=team_id)
        )
    else:
        unlock_query = unlock_query.filter(user=current_user.id)
        
    existing_unlock = unlock_query.first()
    
    if existing_unlock:
        return jsonify({
            'success': False, 
            'message': 'You have already unlocked this path'
        }), 400
    
    # Create unlock record (no points, no solve record - just unlocking).
    # The DB schema requires `user_id` to be non-null, so store the current
    # user as the actor while also setting team_id for team-scoped unlocks.
    unlock_record = ChallengeUnlock(
        user=current_user,
        team=team,
        challenge=matched_flag.unlocks_challenge,
        unlocked_by_flag=matched_flag
    )
    unlock_record.save()
    
    # Get the unlocked challenge details
    unlocked_challenge = matched_flag.unlocks_challenge
    
    # Do NOT modify is_hidden/is_visible - challenge stays hidden globally
    # Visibility is controlled per-user/team via ChallengeUnlock + is_unlocked_for_user()
    
    # Invalidate caches
    cache_service.invalidate_challenge(challenge_id)
    cache_service.invalidate_challenge(str(matched_flag.unlocks_challenge.id))
    
    response_data = {
        'success': True,
        'message': 'Correct flag! New path unlocked!',
        'unlocked_challenges': []
    }
    
    if unlocked_challenge:
        response_data['unlocked_challenges'].append({
            'id': str(unlocked_challenge.id),
            'name': unlocked_challenge.name,
            'category': unlocked_challenge.category
        })
    
    return jsonify(response_data)


@challenges_bp.route('/solves/<string:challenge_id>')
@login_required
def challenge_solves(challenge_id):
    """Get list of teams/users who solved a challenge (Admin only)"""
    # Restrict to admin only - removed public access
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    
    challenge = Challenge.objects.get_or_404(id=challenge_id)
    
    solves = Solve.objects(challenge=challenge).order_by('solved_at')
    
    solve_list = []
    for solve in solves:
        if solve.team:
            team = solve.team
            solve_list.append({
                'name': team.name,
                'type': 'team',
                'solved_at': solve.solved_at.isoformat(),
                'points': solve.points_earned,
                'is_first_blood': solve.is_first_blood
            })
        else:
            user = solve.user
            solve_list.append({
                'name': user.username,
                'type': 'user',
                'solved_at': solve.solved_at.isoformat(),
                'points': solve.points_earned,
                'is_first_blood': solve.is_first_blood
            })
    
    return jsonify({
        'challenge': challenge.name,
        'solves': solve_list
    })
