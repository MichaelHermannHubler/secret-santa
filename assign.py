#!/usr/bin/env python3
"""
CLI script to generate Secret Santa assignments and send the emails.

Usage:
  python assign.py -p PASSWORD                    # generate, then email everyone
  python assign.py -p PASSWORD --skip-email       # generate only
  python assign.py -p PASSWORD --send-only        # (re)send emails to everyone, no new draw
  python assign.py -p PASSWORD --send-only --unsent-only   # only people not yet notified
  python assign.py -p PASSWORD --send-only --to EMAIL      # one person only
"""

import sys
import argparse
from app import (
    app, load_participants, load_assignments, load_config,
    generate_assignments, send_assignment_emails, EmailSendError
)


def send_emails(recipients=None, only_unsent=False):
    print("\n📧 Sending email notifications...")
    try:
        results = send_assignment_emails(recipients=recipients, only_unsent=only_unsent)
    except EmailSendError as error:
        print(f"❌ Error: {error}")
        if not load_config().get('email'):
            print("   Set email configuration in data/config.json")
        return False

    if not results:
        print("  Everyone has already been notified.")
        return True

    for result in results:
        if result['success']:
            print(f"  ✓ Sent to {result['participant']} ({result['email']})")
        else:
            print(f"  ✗ Failed to send to {result['participant']}: {result['message']}")
    sent = sum(1 for result in results if result['success'])
    print(f"\n📧 Email summary: {sent} sent, {len(results) - sent} failed")
    return sent == len(results)


def main():
    parser = argparse.ArgumentParser(description='Generate Secret Santa assignments and send the emails')
    parser.add_argument('--password', '-p', help='Admin password', required=True)
    parser.add_argument('--skip-email', action='store_true', help='Generate assignments without sending emails')
    parser.add_argument('--send-only', action='store_true',
                        help='Do not generate; (re)send emails for the existing assignments')
    parser.add_argument('--to', metavar='EMAIL', help='With --send-only: email only this participant')
    parser.add_argument('--unsent-only', action='store_true',
                        help='With --send-only: skip participants who were already notified')
    args = parser.parse_args()

    if (args.to or args.unsent_only) and not args.send_only:
        parser.error('--to and --unsent-only require --send-only')
    if args.send_only and args.skip_email:
        parser.error('--send-only and --skip-email cannot be combined')

    config = load_config()

    # Verify password
    if args.password != config.get('admin_password', 'admin123'):
        print("❌ Error: Invalid password")
        sys.exit(1)

    if args.send_only:
        recipients = [args.to.strip().lower()] if args.to else None
        sys.exit(0 if send_emails(recipients, args.unsent_only) else 1)

    # Check if assignments already exist
    existing_assignments = load_assignments()
    if existing_assignments:
        response = input("⚠️  Assignments already exist. Do you want to regenerate? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled.")
            sys.exit(0)

    # Generate assignments
    print("🎲 Generating Secret Santa assignments...")
    success, result = generate_assignments()

    if not success:
        print(f"❌ Error: {result}")
        sys.exit(1)

    assignments = result
    participants = load_participants()

    print(f"✅ Successfully generated assignments for {len(assignments)} participants!")
    print("\nAssignments:")
    print("-" * 50)

    # Display assignments
    for participant in participants:
        assignment = assignments.get(participant['email'])
        if assignment:
            giftee = next((p for p in participants if p['email'] == assignment['giftee_email']), None)
            if giftee:
                print(f"{participant['name']} → {giftee['name']}")

    if args.skip_email:
        print("\n⏭️  Skipping email notifications (--skip-email flag used)")
        print("   Send them later with: python assign.py -p PASSWORD --send-only")
    else:
        send_emails()

    print("\n✅ All done! Participants can now check their assignments on the website.")


if __name__ == '__main__':
    # An app context is required so emails are rendered in each
    # participant's registered language (see send_email_notification).
    with app.app_context():
        main()
