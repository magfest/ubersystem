# Visual Regression Test Failures Analysis

## Summary
- **Total screenshots**: ~263
- **Failures**: 46 (17.5%)
- **Fixed**: 4
- **Remaining**: 42

## Fixed Issues (4)

### 1. Binary endpoint (1)
- `registration__qrcode_generator` → marked skip='binary' (returns PNG, not HTML)

### 2. Feature-disabled endpoint (1)
- `statistics__map` → marked skip='requires feature: MAPS_ENABLED' (disabled in test config)

### 3. Null/None rendering bug (1)
- `landing__invalid` → now provides default message "An unknown error occurred." when none is passed

### 4. Template format bug (1)
- `schedule__now` → fixed strftime format codes: `%g:%i` → `%I:%M` (3 occurrences)

## Remaining Failures by Category

### 500 Server Errors (38)
These are application handlers that throw exceptions during visual test:

**Accounts & Auth:**
- `accounts__update_password_of_other`

**Art Show:**
- `art_show_admin__bid_sheet_barcode_generator`
- `art_show_admin__form`
- `art_show_admin__print_check_in_out_form`
- `art_show_admin__record_payment`

**Attractions:**
- `attractions__events`

**Badge Printing:**
- `badge_printing__print_next_badge`

**Budget:**
- `budget__index`

**Dealer Admin:**
- `dealer_admin__convert_example`
- `dealer_admin__dealer_statuses`

**Dev Tools:**
- `devtools__import_model`

**Email Admin:**
- `email_admin__pending_dept`
- `email_admin__pending_examples`

**Indie Games:**
- `indie_arcade__game`
- `indie_retro__game`

**MIVS:**
- `mivs__game`

**Panels:**
- `panels_admin__assigned_to`
- `panels_admin__panel_feedback`
- `panels_admin__panel_poc_schedule`
- `panels_admin__panels_by_poc`

**Preregistration:**
- `preregistration__invalid_badge`
- `preregistration__not_found`

**Reg Admin:**
- `reg_admin__confirm_import_attendees`
- `reg_admin__confirm_import_groups`
- `reg_admin__receipt_items`

**Registration:**
- `registration__check_txn_status`
- `registration__new_checkin`
- `registration__printed_name_problems` (Redis issue)
- `registration__watchlist`

**Reports:**
- `guest_reports__rock_island`

**Shifts Admin:**
- `shifts_admin__staffers_by_job`

**Showcase:**
- `showcase__index`
- `showcase__show_info`
- `showcase_admin__confirm_import_judges`

**Statistics:**
- `statistics__index` (Redis issue)

**Tabletop:**
- `tabletop_checkins__checkout_history`

**Hotel Lottery:**
- `hotel_lottery_admin__history`

### Blank Pages (5)
Page renders with nav but no content (likely missing data or disabled features):
- `dealer_admin__index`
- `guest_reports__index`
- `shifts_admin__all_shifts`
- `staffing_admin__bulk_dept_import`
- `staffing_reports__all_schedules`

### 404 Not Found (1)
- `statistics__map` (fixed - now marked as skip)

## Next Steps

1. **Infrastructure Issues**: Redis not running for 2 tests
   - Solution: Ensure Redis container is available in visual test environment

2. **400 Errors**: Investigate missing parameter handling
   - `registration__check_txn_status` - missing intent_id parameter
   - `registration__new_checkin` - may need proper setup

3. **Complex Handlers**: Require investigation of actual error messages
   - Run with `--tb=long` to see stack traces
   - Likely missing test data fixtures or configuration

4. **Blank Pages**: Likely need populated database records
   - May require DATA_ROUTES entries to provide test objects
   - Or feature enablement in test-defaults.ini

## Test Coverage
Remaining working screenshots: ~217/263 (82.5%)
