# Postmortem: Duplicate User Accounts from Case-Sensitive Email Handling

**Date**: 2026-01-29
**Severity**: Medium
**Status**: Resolved

## Summary

Users reported receiving duplicate email notifications. Investigation revealed multiple user accounts existed with the same email address differing only by case (e.g., `user@example.com` and `User@Example.com`).

## Impact

- 6 users affected with duplicate accounts
- Duplicate email notifications sent to affected users
- User data split across multiple accounts

## Root Cause

The email field in the User model used case-sensitive matching for both:
1. Uniqueness constraint validation
2. User lookup during authentication

This allowed users to create multiple accounts by varying the case of their email address during signup.

## Timeline

- **2026-01-29 08:00** - User report of duplicate notifications received
- **2026-01-29 08:15** - Investigation began via production database
- **2026-01-29 08:30** - Root cause identified: case-sensitive email handling
- **2026-01-29 08:45** - Fix developed and tested locally
- **2026-01-29 09:00** - Fix deployed to production
- **2026-01-29 09:15** - Merge script created to consolidate duplicate accounts
- **2026-01-29 09:30** - All duplicate accounts merged, issue resolved

## Resolution

### Code Changes

1. **Email normalization on creation** (`remarkbox/models/user.py`)
   - Emails now stored as lowercase in `User.__init__`

2. **Case-insensitive lookup** (`remarkbox/models/user.py`)
   - `get_user_by_email()` now uses `func.lower()` for comparison

3. **Merge script** (`remarkbox/scripts/merge_duplicate_email_users.py`)
   - New management command to find and merge duplicate accounts
   - Keeps oldest account, transfers all related data
   - Handles unique constraint conflicts gracefully

### Data Migration

Ran `remarkbox_merge_duplicate_email_users` to consolidate:
- 6 duplicate email sets merged
- 14 nodes transferred
- 4 watchers transferred
- 1 notification transferred
- 6 duplicate accounts deleted
- All emails normalized to lowercase

## Prevention

1. **Unit tests added** (`test_models.py`)
   - `test_email_normalized_to_lowercase`
   - `test_email_mixed_case_normalized`

2. **Integration tests added** (`test_views.py`)
   - `test_get_user_by_email_case_insensitive`
   - `test_get_or_create_returns_existing_regardless_of_case`
   - `test_new_user_email_stored_lowercase`
   - `test_no_duplicate_accounts_from_case_variations`

## Lessons Learned

1. Email addresses should always be normalized to lowercase on input
2. Case-insensitive comparison should be used for email lookups
3. Database unique constraints alone don't prevent case-variant duplicates in SQLite

## Action Items

- [x] Fix email normalization in User model
- [x] Fix case-insensitive email lookup
- [x] Create merge script for existing duplicates
- [x] Add regression tests
- [x] Run merge on production
- [x] Document in postmortem
