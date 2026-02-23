"""
Dev helper: remove act unlock records for a user or team or act.
Usage (from project root, inside virtualenv where app dependencies are installed):

# Remove ACT II unlock for user id 5
python .\scripts\remove_act_unlock.py --act "ACT II" --user 5

# Remove all act unlocks for team id 3
python .\scripts\remove_act_unlock.py --team 3 --all

# Remove all unlocks for a specific act for everyone
python .\scripts\remove_act_unlock.py --act "ACT III" --all

# Remove every act unlock (dangerous)
python .\scripts\remove_act_unlock.py --all --yes-delete-all

This script uses the same application configuration as the app. It must be executed from the project root
so relative imports work and the environment (DATABASE_URL, etc.) is the same.

Note: Intended for development only. Do NOT run on production unless you know what you are doing.
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from models.act_unlock import ActUnlock
from mongoengine.queryset.visitor import Q


def parse_args():
    p = argparse.ArgumentParser(description='Remove ACT unlock records (dev helper)')
    p.add_argument('--act', help='ACT name, e.g. "ACT II"', default=None)
    p.add_argument('--user', type=str, help='User id to filter', default=None)
    p.add_argument('--team', type=str, help='Team id to filter', default=None)
    p.add_argument('--all', action='store_true', help='Delete all matching unlocks (default is to show what would be deleted)')
    p.add_argument('--yes-delete-all', action='store_true', help='When used with --all, skip confirmation (dangerous)')
    p.add_argument('--env', help='FLASK_ENV value to use (development|production|testing)', default=None)
    return p.parse_args()


def main():
    args = parse_args()

    config_name = args.env if args.env else None
    app = create_app(config_name)

    with app.app_context():
        # Build query
        query = Q()
        if args.act:
            query &= Q(act=args.act)
        if args.user is not None:
            query &= Q(user=args.user)
        if args.team is not None:
            query &= Q(team=args.team)

        # Check if any filters were applied
        if not (args.act or args.user or args.team):
            # No filters provided -> select everything
            if not args.all:
                print('No filters provided. Use --all to target all unlocks or provide --user/--team/--act to filter.')
                return

        matches = ActUnlock.objects(query).order_by('unlocked_at')
        
        if not matches:
            print('No matching act unlock records found.')
            return

        print('Found', matches.count(), 'matching act unlock record(s):')
        for m in matches:
            user_id = m.user.id if m.user else None
            team_id = m.team.id if m.team else None
            challenge_id = m.unlocked_by_challenge.id if m.unlocked_by_challenge else None
            print(f' - id={m.id} act={m.act} user_id={user_id} team_id={team_id} unlocked_by_challenge_id={challenge_id} unlocked_at={m.unlocked_at}')

        if not args.all:
            print('\nNo changes made. Re-run with --all to remove the above records.')
            return

        # Confirm deletion
        if not args.yes_delete_all:
            confirm = input('\nType DELETE to permanently remove the above records: ')
            if confirm != 'DELETE':
                print('Aborted. No changes made.')
                return

        # Delete matching records
        try:
            count = matches.delete()
            print(f'Deleted {count} act unlock record(s).')
        except Exception as e:
            print('Error deleting records:', e)


if __name__ == '__main__':
    main()
