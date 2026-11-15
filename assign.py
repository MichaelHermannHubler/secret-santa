#!/usr/bin/env python3
"""
CLI script to trigger Secret Santa assignments
Usage: python assign.py [--password PASSWORD]
"""

import sys
import os
import json
import argparse
from app import (
    app, load_participants, load_assignments, load_config, save_assignments,
    generate_assignments, send_email_notification
)

def main():
    parser = argparse.ArgumentParser(description='Generate Secret Santa assignments')
    parser.add_argument('--password', '-p', help='Admin password', required=True)
    parser.add_argument('--skip-email', action='store_true', help='Skip sending email notifications')
    args = parser.parse_args()
    
    config = load_config()
    
    # Verify password
    if args.password != config.get('admin_password', 'admin123'):
        print("❌ Error: Invalid password")
        sys.exit(1)
    
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
    
    # Send email notifications
    if not args.skip_email:
        print("\n📧 Sending email notifications...")
        email_config = load_config()
        if not email_config.get('email') or not email_config.get('password'):
            print("⚠️  Warning: Email configuration not set. Skipping email notifications.")
            print("   Set email configuration in data/config.json")
        else:
            success_count = 0
            fail_count = 0
            for participant in participants:
                assignment = assignments.get(participant['email'])
                if assignment:
                    giftee = next((p for p in participants if p['email'] == assignment['giftee_email']), None)
                    if giftee:
                        success, message = send_email_notification(
                            participant['email'],
                            participant['name'],
                            giftee['name'],
                            giftee['email'],
                            participant.get('language'),
                            giftee_likes=giftee.get('likes', ''),
                            giftee_dislikes=giftee.get('dislikes', '')
                        )
                        if success:
                            success_count += 1
                            print(f"  ✓ Sent to {participant['name']} ({participant['email']})")
                        else:
                            fail_count += 1
                            print(f"  ✗ Failed to send to {participant['name']}: {message}")
            
            print(f"\n📧 Email summary: {success_count} sent, {fail_count} failed")
    else:
        print("\n⏭️  Skipping email notifications (--skip-email flag used)")
    
    print("\n✅ All done! Participants can now check their assignments on the website.")

if __name__ == '__main__':
    # An app context is required so emails are rendered in each
    # participant's registered language (see send_email_notification).
    with app.app_context():
        main()

