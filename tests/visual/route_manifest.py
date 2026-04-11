"""
Route manifest for visual regression tests.

Each RouteSpec describes one page to screenshot.  The list covers every
CherryPy-exposed route that returns HTML and is reachable without a
specific database object ID.

Auth values:
  'public' - accessible without login (all_renderable(public=True) sections
             or individually public handlers like /accounts/login)
  'admin'  - requires admin login

Common skip reasons:
  'ajax'           - returns JSON, not HTML
  'not_mappable'   - internal CherryPy endpoint
  'file export'    - returns CSV / XLSX / ZIP / PDF
  'redirect only'  - always issues an HTTP redirect, no HTML body
  'requires id'    - crashes or redirects without a specific object id
  'POST only'      - processes a form submission, no GET display
  'binary'         - returns an image or other binary payload
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RouteSpec:
    path: str                       # URL path relative to server root
    label: str                      # Basename used for the baseline image file
    auth: str = 'admin'             # 'public' or 'admin'
    skip: Optional[str] = None      # Non-None → skipped with this reason
    query: str = ''                 # Optional query string appended to path
    wait_selector: Optional[str] = None  # CSS selector to wait for


def _r(path, auth='admin', skip=None, query='', wait=None):
    """Shorthand constructor."""
    label = (path.lstrip('/') + ('?' + query if query else '')).replace('/', '__').replace('?', '_').replace('=', '_').replace('&', '_')
    return RouteSpec(path=path, label=label, auth=auth, skip=skip, query=query, wait_selector=wait)


# ---------------------------------------------------------------------------
# /accounts
# ---------------------------------------------------------------------------
ACCOUNTS = [
    _r('/accounts/login',               auth='public', wait='form'),
    _r('/accounts/reset',               auth='public', wait='form'),
    _r('/accounts/homepage',            wait='body'),
    _r('/accounts/index',               wait='table, h2'),
    _r('/accounts/bulk',                wait='form, h2'),
    _r('/accounts/access_groups',       wait='table, h2'),
    _r('/accounts/change_password',     wait='form'),
    _r('/accounts/update_password_of_other', wait='form'),
    _r('/accounts/sitemap',             wait='ul, h2'),
    _r('/accounts/insert_test_admin',   skip='POST only'),
    _r('/accounts/logout',              skip='redirect only'),
    _r('/accounts/delete',              skip='POST only'),
    _r('/accounts/update',              skip='ajax'),
    _r('/accounts/get_access_group',    skip='ajax'),
    _r('/accounts/delete_access_group', skip='ajax'),
    _r('/accounts/add_bulk_admin_accounts', skip='ajax'),
    _r('/accounts/attendees',           skip='not_mappable'),
    _r('/accounts/process_logout',      skip='not_mappable'),
    _r('/accounts/can_spam',            skip='file export'),
    _r('/accounts/staff_emails',        skip='file export'),
]

# ---------------------------------------------------------------------------
# /api
# ---------------------------------------------------------------------------
API = [
    _r('/api/index',                    wait='table, h2'),
    _r('/api/reference',                wait='h1, h2'),
    _r('/api/api_jobs',                 wait='table, h2'),
    _r('/api/revoke_api_token',         skip='POST only'),
    _r('/api/delete_api_job',           skip='POST only'),
    _r('/api/rerun_api_job',            skip='POST only'),
    _r('/api/requeue_incomplete_jobs',  skip='POST only'),
    _r('/api/create_api_token',         skip='ajax'),
    _r('/api/stripe_webhook_handler',   skip='not_mappable'),
]

# ---------------------------------------------------------------------------
# /art_show_admin
# ---------------------------------------------------------------------------
ART_SHOW_ADMIN = [
    _r('/art_show_admin/index',             wait='table, h2'),
    _r('/art_show_admin/form',              wait='form'),
    _r('/art_show_admin/pieces',            skip='requires id'),
    _r('/art_show_admin/history',           skip='requires id'),
    _r('/art_show_admin/ops',               wait='h2'),
    _r('/art_show_admin/close_out',         wait='h2'),
    _r('/art_show_admin/artist_check_in_out', wait='form, h2'),
    _r('/art_show_admin/print_check_in_out_form', wait='form, h2'),
    _r('/art_show_admin/assign_locations',  wait='h2'),
    _r('/art_show_admin/assignment_map',    wait='h2'),
    _r('/art_show_admin/sales_search',      wait='form, h2'),
    _r('/art_show_admin/bid_sheet_barcode_generator', wait='form, h2'),
    _r('/art_show_admin/bidder_signup',     wait='form, h2'),
    _r('/art_show_admin/record_payment',    wait='form, h2'),
    _r('/art_show_admin/reopen_receipt',    skip='requires id'),
    _r('/art_show_admin/unclaim_piece',     skip='requires id'),
    _r('/art_show_admin/undo_payment',      skip='requires id'),
    _r('/art_show_admin/pieces_bought',     skip='requires id'),
    _r('/art_show_admin/print_artist_invoice', skip='requires id'),
    _r('/art_show_admin/print_bidder_form', skip='requires id'),
    _r('/art_show_admin/print_receipt',     skip='requires id'),
    _r('/art_show_admin/update_piece_status', skip='POST only'),
    _r('/art_show_admin/paid_with_cash',    skip='POST only'),
    _r('/art_show_admin/save_map',          skip='POST only'),
    _r('/art_show_admin/bid_sheet_pdf',     skip='file export'),
    _r('/art_show_admin/validate_app',      skip='ajax'),
    _r('/art_show_admin/validate_bidder_signup', skip='ajax'),
    _r('/art_show_admin/validate_check_in_out', skip='ajax'),
    _r('/art_show_admin/cancel_payment',    skip='ajax'),
    _r('/art_show_admin/purchases_charge',  skip='ajax'),
    _r('/art_show_admin/record_terminal_payment', skip='ajax'),
    _r('/art_show_admin/save_and_check_in_out', skip='ajax'),
    _r('/art_show_admin/sign_up_bidder',    skip='ajax'),
    _r('/art_show_admin/start_terminal_payment', skip='ajax'),
    _r('/art_show_admin/unassign_location', skip='ajax'),
    _r('/art_show_admin/update_all',        skip='ajax'),
    _r('/art_show_admin/update_location',   skip='ajax'),
]

# ---------------------------------------------------------------------------
# /art_show_applications  (public)
# ---------------------------------------------------------------------------
ART_SHOW_APPLICATIONS = [
    _r('/art_show_applications/index',      auth='public', wait='form, h2'),
    _r('/art_show_applications/edit',       auth='public', skip='requires id'),
    _r('/art_show_applications/confirm_pieces', auth='public', skip='requires id'),
    _r('/art_show_applications/confirmation', auth='public', skip='requires id'),
    _r('/art_show_applications/mailing_address', auth='public', skip='requires id'),
    _r('/art_show_applications/bidder_signup', auth='public', wait='form, h2'),
    _r('/art_show_applications/add_agent_code', auth='public', skip='POST only'),
    _r('/art_show_applications/cancel_agent_code', auth='public', skip='POST only'),
    _r('/art_show_applications/new_agent_app', auth='public', skip='POST only'),
    _r('/art_show_applications/finish_pending_payment', auth='public', skip='ajax'),
    _r('/art_show_applications/process_art_show_payment', auth='public', skip='ajax'),
    _r('/art_show_applications/remove_art_show_piece', auth='public', skip='ajax'),
    _r('/art_show_applications/save_art_show_piece', auth='public', skip='ajax'),
    _r('/art_show_applications/validate_app', auth='public', skip='ajax'),
    _r('/art_show_applications/validate_art_show_piece', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /art_show_reports
# ---------------------------------------------------------------------------
ART_SHOW_REPORTS = [
    _r('/art_show_reports/index',           wait='h2'),
    _r('/art_show_reports/sales_invoices',  wait='table, h2'),
    _r('/art_show_reports/artist_invoices', wait='table, h2'),
    _r('/art_show_reports/high_bids',       wait='table, h2'),
    _r('/art_show_reports/pieces_by_status', wait='table, h2'),
    _r('/art_show_reports/artists_by_payout', wait='table, h2'),
    _r('/art_show_reports/summary',         wait='table, h2'),
    _r('/art_show_reports/auction_report',  wait='table, h2'),
    _r('/art_show_reports/artist_receipt_discrepancies', wait='table, h2'),
    _r('/art_show_reports/artists_nonzero_balance', wait='table, h2'),
    _r('/art_show_reports/unpicked_up_pieces', skip='file export'),
    _r('/art_show_reports/artist_csv',      skip='file export'),
    _r('/art_show_reports/approved_international_artists', skip='file export'),
    _r('/art_show_reports/banner_csv',      skip='file export'),
    _r('/art_show_reports/bidder_csv',      skip='file export'),
    _r('/art_show_reports/pieces_csv',      skip='file export'),
]

# ---------------------------------------------------------------------------
# /attractions  (public)
# ---------------------------------------------------------------------------
ATTRACTIONS = [
    _r('/attractions/index',        auth='public', wait='h2'),
    _r('/attractions/features',     auth='public', wait='h2'),
    _r('/attractions/events',       auth='public', wait='h2'),
    _r('/attractions/manage',       auth='public', wait='h2'),
    _r('/attractions/default',      auth='public', skip='requires slug'),
    _r('/attractions/cancel_signup', auth='public', skip='ajax'),
    _r('/attractions/notification_pref', auth='public', skip='ajax'),
    _r('/attractions/opt_out',      auth='public', skip='ajax'),
    _r('/attractions/signup_for_event', auth='public', skip='ajax'),
    _r('/attractions/verify_badge_num', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /attractions_admin
# ---------------------------------------------------------------------------
ATTRACTIONS_ADMIN = [
    _r('/attractions_admin/index',          wait='table, h2'),
    _r('/attractions_admin/form',           wait='form'),
    _r('/attractions_admin/new',            wait='form'),
    _r('/attractions_admin/feature',        skip='requires id'),
    _r('/attractions_admin/event',          skip='requires id'),
    _r('/attractions_admin/checkin',        wait='form, h2'),
    _r('/attractions_admin/import_attractions', wait='form, h2'),
    _r('/attractions_admin/delete',         skip='POST only'),
    _r('/attractions_admin/export_feature', skip='file export'),
    _r('/attractions_admin/signups_export', skip='file export'),
    _r('/attractions_admin/cancel_signup',  skip='ajax'),
    _r('/attractions_admin/checkin_signup', skip='ajax'),
    _r('/attractions_admin/close_signups',  skip='ajax'),
    _r('/attractions_admin/delete_event',   skip='ajax'),
    _r('/attractions_admin/delete_event_cascade', skip='ajax'),
    _r('/attractions_admin/delete_feature', skip='ajax'),
    _r('/attractions_admin/delete_feature_cascade', skip='ajax'),
    _r('/attractions_admin/edit_event_gap', skip='not_mappable'),
    _r('/attractions_admin/get_signups',    skip='ajax'),
    _r('/attractions_admin/open_signups',   skip='ajax'),
    _r('/attractions_admin/pull_from_waitlist', skip='ajax'),
    _r('/attractions_admin/sign_up',        skip='ajax'),
    _r('/attractions_admin/undo_checkin_signup', skip='ajax'),
    _r('/attractions_admin/update_locations', skip='ajax'),
    _r('/attractions_admin/validate_attraction', skip='ajax'),
    _r('/attractions_admin/validate_event', skip='ajax'),
    _r('/attractions_admin/validate_feature', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /badge_exports  (all file exports)
# ---------------------------------------------------------------------------
BADGE_EXPORTS = [
    _r('/badge_exports/badge_hangars_supporters', skip='file export'),
    _r('/badge_exports/personalized_badges_zip', skip='file export'),
    _r('/badge_exports/printed_badges_attendee', skip='file export'),
    _r('/badge_exports/printed_badges_guest', skip='file export'),
    _r('/badge_exports/printed_badges_minor', skip='file export'),
    _r('/badge_exports/printed_badges_one_day', skip='file export'),
    _r('/badge_exports/printed_badges_staff', skip='file export'),
    _r('/badge_exports/printed_badges_staff__expert_mode_only', skip='file export'),
]

# ---------------------------------------------------------------------------
# /badge_printing
# ---------------------------------------------------------------------------
BADGE_PRINTING = [
    _r('/badge_printing/index',             wait='h2'),
    _r('/badge_printing/print_jobs_list',   wait='table, h2'),
    _r('/badge_printing/attendee_print_jobs', skip='requires id'),
    _r('/badge_printing/badge_waiting',     wait='h2'),
    _r('/badge_printing/print_next_badge',  wait='h2'),
    _r('/badge_printing/mark_as_invalid',   skip='POST only'),
    _r('/badge_printing/mark_as_printed',   skip='POST only'),
    _r('/badge_printing/mark_as_unsent',    skip='POST only'),
    _r('/badge_printing/print_jobs',        skip='not_mappable'),
    _r('/badge_printing/add_job_to_queue',  skip='ajax'),
]

# ---------------------------------------------------------------------------
# /band_admin
# ---------------------------------------------------------------------------
BAND_ADMIN = [
    _r('/band_admin/index',                 skip='redirect only'),
]

# ---------------------------------------------------------------------------
# /barcode
# ---------------------------------------------------------------------------
BARCODE = [
    _r('/barcode/index',                    wait='form, h2'),
    _r('/barcode/get_badge_num_from_barcode', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /budget
# ---------------------------------------------------------------------------
BUDGET = [
    _r('/budget/index',                     wait='table, h2'),
    _r('/budget/badge_cost_summary',        wait='table, h2'),
    _r('/budget/dealer_cost_summary',       wait='table, h2'),
    _r('/budget/attendee_addon_summary',    wait='table, h2'),
    _r('/budget/mpoints',                   wait='table, h2'),
    _r('/budget/view_promo_codes',          wait='table, h2'),
    _r('/budget/generate_promo_codes',      wait='form'),
]

# ---------------------------------------------------------------------------
# /dealer_admin
# ---------------------------------------------------------------------------
DEALER_ADMIN = [
    _r('/dealer_admin/index',               wait='table, h2'),
    _r('/dealer_admin/waitlist',            wait='table, h2'),
    _r('/dealer_admin/dealer_statuses',     wait='table, h2'),
    _r('/dealer_admin/convert_example',     wait='h2'),
    _r('/dealer_admin/convert_declined',    skip='POST only'),
    _r('/dealer_admin/send_signnow_link',   skip='POST only'),
    _r('/dealer_admin/set_table_shared',    skip='ajax'),
    _r('/dealer_admin/unapprove',           skip='ajax'),
]

# ---------------------------------------------------------------------------
# /dealer_reports
# ---------------------------------------------------------------------------
DEALER_REPORTS = [
    _r('/dealer_reports/dealer_receipt_discrepancies', wait='table, h2'),
    _r('/dealer_reports/dealers_nonzero_balance', wait='table, h2'),
    _r('/dealer_reports/all_sellers_application_info', skip='file export'),
    _r('/dealer_reports/approved_seller_table_info', skip='file export'),
    _r('/dealer_reports/seller_applications', skip='file export'),
    _r('/dealer_reports/seller_comptroller_info', skip='file export'),
    _r('/dealer_reports/seller_initial_review', skip='file export'),
    _r('/dealer_reports/seller_tax_info', skip='file export'),
    _r('/dealer_reports/waitlisted_group_info', skip='file export'),
]

# ---------------------------------------------------------------------------
# /dept_admin
# ---------------------------------------------------------------------------
DEPT_ADMIN = [
    _r('/dept_admin/index',                 wait='table, h2'),
    _r('/dept_admin/form',                  wait='form'),
    _r('/dept_admin/new',                   wait='form'),
    _r('/dept_admin/requests',              wait='table, h2'),
    _r('/dept_admin/role',                  skip='requires id'),
    _r('/dept_admin/overworked_attendees',  skip='file export'),
    _r('/dept_admin/assign_member',         skip='requires id'),
    _r('/dept_admin/unassign_member',       skip='POST only'),
    _r('/dept_admin/delete',                skip='POST only'),
    _r('/dept_admin/delete_role',           skip='POST only'),
    _r('/dept_admin/dept_members_export',   skip='file export'),
    _r('/dept_admin/dept_requests_export',  skip='file export'),
    _r('/dept_admin/set_inherent_role',     skip='ajax'),
    _r('/dept_admin/validate_department',   skip='ajax'),
]

# ---------------------------------------------------------------------------
# /dept_checklist
# ---------------------------------------------------------------------------
DEPT_CHECKLIST = [
    _r('/dept_checklist/index',             wait='table, h2'),
    _r('/dept_checklist/overview',          wait='table, h2'),
    _r('/dept_checklist/form',              skip='requires id'),
    _r('/dept_checklist/item',              skip='requires id'),
    _r('/dept_checklist/placeholders',      wait='table, h2'),
    _r('/dept_checklist/printed_signs',     wait='h2'),
    _r('/dept_checklist/bulk_print_jobs',   wait='table, h2'),
    _r('/dept_checklist/hotel_eligible',    wait='table, h2'),
    _r('/dept_checklist/hotel_requests',    wait='table, h2'),
    _r('/dept_checklist/hours',             wait='table, h2'),
    _r('/dept_checklist/no_shows',          wait='table, h2'),
    _r('/dept_checklist/allotments',        wait='table, h2'),
    _r('/dept_checklist/treasury',          wait='h2'),
    _r('/dept_checklist/guidebook_schedule', wait='h2'),
    _r('/dept_checklist/mark_item_complete', skip='POST only'),
    _r('/dept_checklist/delete_print_request', skip='POST only'),
    _r('/dept_checklist/bulk_print_jobs_csv', skip='file export'),
    _r('/dept_checklist/item_csv',          skip='file export'),
    _r('/dept_checklist/overview_xlsx',     skip='file export'),
    _r('/dept_checklist/approve',           skip='ajax'),
    _r('/dept_checklist/validate_bulk_printing_request', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /devtools
# ---------------------------------------------------------------------------
DEVTOOLS = [
    _r('/devtools/index',                   wait='h2'),
    _r('/devtools/gitinfo',                 wait='h2, pre'),
    _r('/devtools/dump_diagnostics',        wait='h2, pre'),
    _r('/devtools/csv_import',              wait='form'),
    _r('/devtools/import_model',            wait='form, h2'),
    _r('/devtools/csv_export',              wait='form, h2'),
    _r('/devtools/health',                  wait='h2'),
    _r('/devtools/export_model',            skip='file export'),
]

# ---------------------------------------------------------------------------
# /email_admin
# ---------------------------------------------------------------------------
EMAIL_ADMIN = [
    _r('/email_admin/index',                wait='form, h2'),
    _r('/email_admin/sent',                 wait='table, h2'),
    _r('/email_admin/pending',              wait='table, h2'),
    _r('/email_admin/pending_dept',         wait='table, h2'),
    _r('/email_admin/pending_examples',     wait='table, h2'),
    _r('/email_admin/test_email',           wait='form'),
    _r('/email_admin/emails_by_interest',   wait='table, h2'),
    _r('/email_admin/emails_by_kickin',     wait='table, h2'),
    _r('/email_admin/approve',              skip='POST only'),
    _r('/email_admin/unapprove',            skip='POST only'),
    _r('/email_admin/update_dates',         skip='POST only'),
    _r('/email_admin/reset_fixture_attr',   skip='POST only'),
    _r('/email_admin/emails_by_interest_csv', skip='file export'),
    _r('/email_admin/emails_by_kickin_csv', skip='file export'),
    _r('/email_admin/resend_email',         skip='ajax'),
]

# ---------------------------------------------------------------------------
# /group_admin
# ---------------------------------------------------------------------------
GROUP_ADMIN = [
    _r('/group_admin/index',                wait='table, h2'),
    _r('/group_admin/form',                 wait='form'),
    _r('/group_admin/history',              skip='requires id'),
    _r('/group_admin/deletion_confirmation', skip='requires id'),
    _r('/group_admin/checklist_info',       skip='requires id'),
    _r('/group_admin/new_group_from_attendee', skip='POST only'),
    _r('/group_admin/assign_leader',        skip='POST only'),
    _r('/group_admin/paid_with_cash',       skip='POST only'),
    _r('/group_admin/delete',               skip='POST only'),
    _r('/group_admin/validate_group',       skip='ajax'),
]

# ---------------------------------------------------------------------------
# /guest_admin
# ---------------------------------------------------------------------------
GUEST_ADMIN = [
    _r('/guest_admin/index',                skip='redirect only'),
]

# ---------------------------------------------------------------------------
# /guest_reports
# ---------------------------------------------------------------------------
GUEST_REPORTS = [
    _r('/guest_reports/index',              wait='h2'),
    _r('/guest_reports/rock_island',        wait='table, h2'),
    _r('/guest_reports/autograph_requests', skip='file export'),
    _r('/guest_reports/checklist_info_csv', skip='file export'),
    _r('/guest_reports/detailed_travel_info_csv', skip='file export'),
    _r('/guest_reports/panel_info_csv',     skip='file export'),
    _r('/guest_reports/rock_island_csv',    skip='file export'),
    _r('/guest_reports/rock_island_image_zip', skip='file export'),
    _r('/guest_reports/rock_island_info_csv', skip='file export'),
    _r('/guest_reports/rock_island_square_xlsx', skip='file export'),
]

# ---------------------------------------------------------------------------
# /guests  (public — performer portal)
# ---------------------------------------------------------------------------
GUESTS = [
    _r('/guests/index',     auth='public', skip='requires performer login'),
    _r('/guests/agreement', auth='public', skip='requires performer login'),
    _r('/guests/bio',       auth='public', skip='requires performer login'),
    _r('/guests/taxes',     auth='public', skip='requires performer login'),
    _r('/guests/stage_plot', auth='public', skip='requires performer login'),
    _r('/guests/panel',     auth='public', skip='requires performer login'),
    _r('/guests/mc',        auth='public', skip='requires performer login'),
    _r('/guests/rehearsal', auth='public', skip='requires performer login'),
    _r('/guests/travel_plans', auth='public', skip='requires performer login'),
    _r('/guests/hospitality', auth='public', skip='requires performer login'),
    _r('/guests/merch',     auth='public', skip='requires performer login'),
    _r('/guests/charity',   auth='public', skip='requires performer login'),
    _r('/guests/autograph', auth='public', skip='requires performer login'),
    _r('/guests/interview', auth='public', skip='requires performer login'),
    _r('/guests/media_request', auth='public', skip='requires performer login'),
    _r('/guests/performer_badges', auth='public', skip='requires performer login'),
    _r('/guests/w9',        auth='public', skip='requires performer login'),
    _r('/guests/update_arrival_plans', auth='public', skip='requires performer login'),
    _r('/guests/view_image', auth='public', skip='requires id'),
    _r('/guests/view_track', auth='public', skip='requires id'),
    _r('/guests/view_inventory_file', auth='public', skip='requires id'),
    _r('/guests/decline_panel', auth='public', skip='POST only'),
    _r('/guests/delete_sample_track', auth='public', skip='ajax'),
    _r('/guests/remove_inventory_item', auth='public', skip='ajax'),
    _r('/guests/save_inventory_item', auth='public', skip='ajax'),
    # mivs_* sub-pages also require performer login
    _r('/guests/mivs_core_hours', auth='public', skip='requires performer login'),
    _r('/guests/mivs_discussion', auth='public', skip='requires performer login'),
    _r('/guests/mivs_handbook', auth='public', skip='requires performer login'),
    _r('/guests/mivs_hotel_space', auth='public', skip='requires performer login'),
    _r('/guests/mivs_logistics', auth='public', skip='requires performer login'),
    _r('/guests/mivs_selling_at_event', auth='public', skip='requires performer login'),
    _r('/guests/mivs_show_info', auth='public', skip='requires performer login'),
    _r('/guests/mivs_training', auth='public', skip='requires performer login'),
]

# ---------------------------------------------------------------------------
# /hotel_lottery  (public — attendee lottery portal)
# ---------------------------------------------------------------------------
HOTEL_LOTTERY = [
    _r('/hotel_lottery/start',          auth='public', wait='h2'),
    _r('/hotel_lottery/terms',          auth='public', wait='h2'),
    _r('/hotel_lottery/index',          auth='public', wait='form, h2'),
    _r('/hotel_lottery/room_lottery',   auth='public', wait='h2'),
    _r('/hotel_lottery/suite_lottery',  auth='public', wait='h2'),
    _r('/hotel_lottery/room_group',     auth='public', skip='requires id'),
    _r('/hotel_lottery/secure_room',    auth='public', skip='requires id'),
    _r('/hotel_lottery/edit_room',      auth='public', skip='requires id'),
    _r('/hotel_lottery/confirm',        auth='public', skip='requires id'),
    _r('/hotel_lottery/decline',        auth='public', skip='requires id'),
    _r('/hotel_lottery/accept_invite',  auth='public', skip='requires id'),
    _r('/hotel_lottery/cancel_invite',  auth='public', skip='POST only'),
    _r('/hotel_lottery/delete_group',   auth='public', skip='POST only'),
    _r('/hotel_lottery/enter_attendee_lottery', auth='public', skip='POST only'),
    _r('/hotel_lottery/guarantee_confirm', auth='public', skip='requires id'),
    _r('/hotel_lottery/invite_room_guest', auth='public', skip='requires id'),
    _r('/hotel_lottery/join_group',     auth='public', skip='requires id'),
    _r('/hotel_lottery/leave_group',    auth='public', skip='POST only'),
    _r('/hotel_lottery/new_invite_code', auth='public', skip='POST only'),
    _r('/hotel_lottery/reenter_lottery', auth='public', skip='POST only'),
    _r('/hotel_lottery/remove_group_member', auth='public', skip='POST only'),
    _r('/hotel_lottery/remove_room_guest', auth='public', skip='POST only'),
    _r('/hotel_lottery/save_group',     auth='public', skip='POST only'),
    _r('/hotel_lottery/send_room_invite', auth='public', skip='POST only'),
    _r('/hotel_lottery/switch_entry_type', auth='public', skip='POST only'),
    _r('/hotel_lottery/transfer_leadership', auth='public', skip='POST only'),
    _r('/hotel_lottery/update_contact_info', auth='public', skip='POST only'),
    _r('/hotel_lottery/withdraw_entry', auth='public', skip='POST only'),
    _r('/hotel_lottery/room_group_search', auth='public', skip='ajax'),
    _r('/hotel_lottery/save_card_token', auth='public', skip='ajax'),
    _r('/hotel_lottery/secure_room_callback', auth='public', skip='ajax'),
    _r('/hotel_lottery/validate_hotel_lottery', auth='public', skip='ajax'),
    _r('/hotel_lottery/vault_webhook',  auth='public', skip='not_mappable'),
]

# ---------------------------------------------------------------------------
# /hotel_lottery_admin
# ---------------------------------------------------------------------------
HOTEL_LOTTERY_ADMIN = [
    _r('/hotel_lottery_admin/index',            wait='table, h2'),
    _r('/hotel_lottery_admin/manage_hotels',    wait='table, h2'),
    _r('/hotel_lottery_admin/manage_room_types', wait='table, h2'),
    _r('/hotel_lottery_admin/manage_inventory', wait='table, h2'),
    _r('/hotel_lottery_admin/manage_partitions', wait='table, h2'),
    _r('/hotel_lottery_admin/settings',         wait='form, h2'),
    _r('/hotel_lottery_admin/form',             wait='form'),
    _r('/hotel_lottery_admin/feed',             wait='h2'),
    _r('/hotel_lottery_admin/history',          wait='table, h2'),
    _r('/hotel_lottery_admin/lottery_runs',     wait='table, h2'),
    _r('/hotel_lottery_admin/assigned_entries', skip='file export'),
    _r('/hotel_lottery_admin/accepted_dealers', skip='file export'),
    _r('/hotel_lottery_admin/setup_vault_form', wait='form, h2'),
    _r('/hotel_lottery_admin/edit_hotel',       skip='requires id'),
    _r('/hotel_lottery_admin/edit_room_type',   skip='requires id'),
    _r('/hotel_lottery_admin/edit_inventory_item', skip='requires id'),
    _r('/hotel_lottery_admin/edit_partition',   skip='requires id'),
    _r('/hotel_lottery_admin/lottery_run_detail', skip='requires id'),
    _r('/hotel_lottery_admin/run_lottery',      skip='requires id'),
    _r('/hotel_lottery_admin/award_run',        skip='POST only'),
    _r('/hotel_lottery_admin/delete_run',       skip='POST only'),
    _r('/hotel_lottery_admin/revert_run',       skip='POST only'),
    _r('/hotel_lottery_admin/update_lottery_run', skip='POST only'),
    _r('/hotel_lottery_admin/hotel_inventory_xlsx', skip='file export'),
    _r('/hotel_lottery_admin/hotel_inventory_zip', skip='file export'),
    _r('/hotel_lottery_admin/export_tracking',  skip='file export'),
    _r('/hotel_lottery_admin/interchange_export', skip='file export'),
    _r('/hotel_lottery_admin/bulk_unlock',      skip='ajax'),
    _r('/hotel_lottery_admin/inventory_assignees', skip='ajax'),
    _r('/hotel_lottery_admin/process_waitlist', skip='ajax'),
    _r('/hotel_lottery_admin/reduce_awards',    skip='ajax'),
    _r('/hotel_lottery_admin/unlock_application', skip='ajax'),
    _r('/hotel_lottery_admin/validate_hotel_lottery', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /hotel_reports
# ---------------------------------------------------------------------------
HOTEL_REPORTS = [
    _r('/hotel_reports/setup_teardown',     wait='table, h2'),
    _r('/hotel_reports/inconsistent_shoulder_shifts', wait='table, h2'),
    _r('/hotel_reports/hours_vs_rooms',     wait='table, h2'),
    _r('/hotel_reports/hours_vs_rooms_by_dept', wait='table, h2'),
    _r('/hotel_reports/hotel_audit',        skip='file export'),
    _r('/hotel_reports/gaylord',            skip='file export'),
    _r('/hotel_reports/mark_center',        skip='file export'),
    _r('/hotel_reports/ordered',            skip='file export'),
    _r('/hotel_reports/hotel_email_info',   skip='file export'),
    _r('/hotel_reports/attendee_hotel_pins', skip='file export'),
    _r('/hotel_reports/hours_vs_rooms_csv', skip='file export'),
    _r('/hotel_reports/hours_vs_rooms_by_dept_csv', skip='file export'),
    _r('/hotel_reports/inconsistent_shoulder_shifts_csv', skip='file export'),
]

# ---------------------------------------------------------------------------
# /indie_arcade  (public)
# ---------------------------------------------------------------------------
INDIE_ARCADE = [
    _r('/indie_arcade/game',            auth='public', wait='form'),
    _r('/indie_arcade/photo',           auth='public', skip='requires id'),
    _r('/indie_arcade/confirm',         auth='public', skip='requires id'),
    _r('/indie_arcade/delete_photo',    auth='public', skip='POST only'),
    _r('/indie_arcade/validate_game',   auth='public', skip='ajax'),
    _r('/indie_arcade/validate_image',  auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /indie_arcade_reports
# ---------------------------------------------------------------------------
INDIE_ARCADE_REPORTS = [
    _r('/indie_arcade_reports/everything', skip='file export'),
    _r('/indie_arcade_reports/judges',     skip='file export'),
    _r('/indie_arcade_reports/presenters', skip='file export'),
]

# ---------------------------------------------------------------------------
# /indie_retro  (public)
# ---------------------------------------------------------------------------
INDIE_RETRO = [
    _r('/indie_retro/game',             auth='public', wait='form'),
    _r('/indie_retro/screenshot',       auth='public', skip='requires id'),
    _r('/indie_retro/confirm',          auth='public', skip='requires id'),
    _r('/indie_retro/delete_screenshot', auth='public', skip='POST only'),
    _r('/indie_retro/validate_game',    auth='public', skip='ajax'),
    _r('/indie_retro/validate_image',   auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /indie_retro_reports
# ---------------------------------------------------------------------------
INDIE_RETRO_REPORTS = [
    _r('/indie_retro_reports/everything', skip='file export'),
    _r('/indie_retro_reports/judges',     skip='file export'),
    _r('/indie_retro_reports/presenters', skip='file export'),
]

# ---------------------------------------------------------------------------
# /landing  (public)
# ---------------------------------------------------------------------------
LANDING = [
    _r('/landing/index',    auth='public', wait='body'),
    _r('/landing/invalid',  auth='public', wait='body'),
]

# ---------------------------------------------------------------------------
# /marketplace  (public)
# ---------------------------------------------------------------------------
MARKETPLACE = [
    _r('/marketplace/apply',            auth='public', wait='form'),
    _r('/marketplace/edit',             auth='public', skip='requires id'),
    _r('/marketplace/confirmation',     auth='public', skip='requires id'),
    _r('/marketplace/cancel',           auth='public', skip='requires id'),
    _r('/marketplace/process_marketplace_payment', auth='public', skip='ajax'),
    _r('/marketplace/validate_marketplace_app', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /marketplace_admin
# ---------------------------------------------------------------------------
MARKETPLACE_ADMIN = [
    _r('/marketplace_admin/index',      wait='table, h2'),
    _r('/marketplace_admin/form',       skip='requires id'),
    _r('/marketplace_admin/history',    skip='requires id'),
    _r('/marketplace_admin/set_status', skip='POST only'),
    _r('/marketplace_admin/all_applications', skip='file export'),
    _r('/marketplace_admin/validate_marketplace_app', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /merch_admin
# ---------------------------------------------------------------------------
MERCH_ADMIN = [
    _r('/merch_admin/index',                    wait='form, h2'),
    _r('/merch_admin/multi_merch_pickup',       wait='form, h2'),
    _r('/merch_admin/arbitrary_charge_form',    wait='form'),
    _r('/merch_admin/arbitrary_charge',         skip='ajax'),
    _r('/merch_admin/cancel_arbitrary_charge',  skip='ajax'),
    _r('/merch_admin/check_merch',              skip='ajax'),
    _r('/merch_admin/give_merch',               skip='ajax'),
    _r('/merch_admin/log_in_volunteer',         skip='ajax'),
    _r('/merch_admin/record_mpoint_cashout',    skip='ajax'),
    _r('/merch_admin/record_old_mpoint_exchange', skip='ajax'),
    _r('/merch_admin/record_sale',              skip='ajax'),
    _r('/merch_admin/redeem_merch_discount',    skip='ajax'),
    _r('/merch_admin/take_back_merch',          skip='ajax'),
    _r('/merch_admin/undo_mpoint_cashout',      skip='ajax'),
    _r('/merch_admin/undo_mpoint_exchange',     skip='ajax'),
    _r('/merch_admin/undo_sale',                skip='ajax'),
]

# ---------------------------------------------------------------------------
# /merch_reports
# ---------------------------------------------------------------------------
MERCH_REPORTS = [
    _r('/merch_reports/shirt_manufacturing_counts', wait='table, h2'),
    _r('/merch_reports/shirt_counts',           wait='table, h2'),
    _r('/merch_reports/extra_merch',            wait='table, h2'),
    _r('/merch_reports/owed_merch',             wait='table, h2'),
    _r('/merch_reports/owed_merch_csv',         skip='file export'),
]

# ---------------------------------------------------------------------------
# /mits  (public — MITS team portal)
# ---------------------------------------------------------------------------
MITS = [
    _r('/mits/index',               auth='public', wait='form, h2'),
    _r('/mits/login_explanation',   auth='public', wait='h2'),
    _r('/mits/check_if_applied',    auth='public', wait='form, h2'),
    _r('/mits/continue_app',        auth='public', skip='requires id'),
    _r('/mits/team',                auth='public', skip='requires mits login'),
    _r('/mits/applicant',           auth='public', skip='requires mits login'),
    _r('/mits/game',                auth='public', skip='requires mits login'),
    _r('/mits/hotel_requests',      auth='public', skip='requires mits login'),
    _r('/mits/panel',               auth='public', skip='requires mits login'),
    _r('/mits/schedule',            auth='public', skip='requires mits login'),
    _r('/mits/waiver',              auth='public', skip='requires mits login'),
    _r('/mits/accepted_teams',      auth='public', skip='requires mits login'),
    _r('/mits/cancel',              auth='public', skip='POST only'),
    _r('/mits/uncancel',            auth='public', skip='POST only'),
    _r('/mits/logout',              auth='public', skip='redirect only'),
    _r('/mits/delete_applicant',    auth='public', skip='POST only'),
    _r('/mits/delete_game',         auth='public', skip='POST only'),
    _r('/mits/set_primary_contact', auth='public', skip='POST only'),
    _r('/mits/submit_for_judging',  auth='public', skip='POST only'),
    _r('/mits/delete_document',     auth='public', skip='ajax'),
    _r('/mits/delete_picture',      auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /mits_admin
# ---------------------------------------------------------------------------
MITS_ADMIN = [
    _r('/mits_admin/index',             wait='table, h2'),
    _r('/mits_admin/accepted',          wait='table, h2'),
    _r('/mits_admin/teams_and_badges',  wait='table, h2'),
    _r('/mits_admin/badges',            wait='table, h2'),
    _r('/mits_admin/hotel_requests',    skip='file export'),
    _r('/mits_admin/panel_requests',    skip='file export'),
    _r('/mits_admin/showcase_requests', skip='file export'),
    _r('/mits_admin/tournament_interest', skip='file export'),
    _r('/mits_admin/team',              skip='requires id'),
    _r('/mits_admin/create_new_application', skip='POST only'),
    _r('/mits_admin/delete_team',       skip='POST only'),
    _r('/mits_admin/set_status',        skip='POST only'),
    _r('/mits_admin/accepted_games_images_zip', skip='file export'),
    _r('/mits_admin/create_badge',      skip='ajax'),
    _r('/mits_admin/link_badge',        skip='ajax'),
]

# ---------------------------------------------------------------------------
# /mivs  (public — MIVS game dev portal)
# ---------------------------------------------------------------------------
MIVS = [
    _r('/mivs/game',            auth='public', wait='form'),
    _r('/mivs/update_demo_info', auth='public', skip='requires id'),
    _r('/mivs/code',            auth='public', skip='requires id'),
    _r('/mivs/screenshot',      auth='public', skip='requires id'),
    _r('/mivs/delete_screenshot', auth='public', skip='POST only'),
    _r('/mivs/delete_code',     auth='public', skip='POST only'),
    _r('/mivs/validate_code',   auth='public', skip='ajax'),
    _r('/mivs/validate_game',   auth='public', skip='ajax'),
    _r('/mivs/validate_image',  auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /mivs_judging
# ---------------------------------------------------------------------------
MIVS_JUDGING = [
    _r('/mivs_judging/index',           wait='table, h2'),
]

# ---------------------------------------------------------------------------
# /mivs_reports
# ---------------------------------------------------------------------------
MIVS_REPORTS = [
    _r('/mivs_reports/everything',          skip='file export'),
    _r('/mivs_reports/judges',              skip='file export'),
    _r('/mivs_reports/presenters',          skip='file export'),
    _r('/mivs_reports/accepted_games_xlsx', skip='file export'),
    _r('/mivs_reports/accepted_games_zip',  skip='file export'),
    _r('/mivs_reports/checklist_info_csv',  skip='file export'),
    _r('/mivs_reports/discussion_group_emails', skip='file export'),
    _r('/mivs_reports/show_info_csv',       skip='file export'),
    _r('/mivs_reports/social_media',        skip='file export'),
]

# ---------------------------------------------------------------------------
# /other_reports
# ---------------------------------------------------------------------------
OTHER_REPORTS = [
    _r('/other_reports/food_restrictions',      wait='table, h2'),
    _r('/other_reports/food_eligible',          skip='file export'),
    _r('/other_reports/cash_handlers',          skip='file export'),
    _r('/other_reports/guest_donations',        wait='table, h2'),
    _r('/other_reports/requested_accessibility_services', skip='file export'),
]

# ---------------------------------------------------------------------------
# /panels  (public)
# ---------------------------------------------------------------------------
PANELS = [
    _r('/panels/index',             auth='public', wait='form'),
    _r('/panels/confirm_panel',     auth='public', skip='POST only'),
    _r('/panels/validate_panel_app', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /panels_admin
# ---------------------------------------------------------------------------
PANELS_ADMIN = [
    _r('/panels_admin/index',           wait='table, h2'),
    _r('/panels_admin/app',             skip='requires id'),
    _r('/panels_admin/form',            skip='requires id'),
    _r('/panels_admin/edit_panelist',   skip='requires id'),
    _r('/panels_admin/email_statuses',  wait='table, h2'),
    _r('/panels_admin/assigned_to',     wait='table, h2'),
    _r('/panels_admin/feedback_report', wait='table, h2'),
    _r('/panels_admin/panel_feedback',  wait='table, h2'),
    _r('/panels_admin/panels_by_poc',   skip='file export'),
    _r('/panels_admin/panel_poc_schedule', wait='table, h2'),
    _r('/panels_admin/badges',          wait='table, h2'),
    _r('/panels_admin/everything',      skip='file export'),
    _r('/panels_admin/assign_guest',    skip='POST only'),
    _r('/panels_admin/associate',       skip='POST only'),
    _r('/panels_admin/change_submitter', skip='POST only'),
    _r('/panels_admin/mark',            skip='POST only'),
    _r('/panels_admin/remove_panelist', skip='POST only'),
    _r('/panels_admin/set_poc',         skip='POST only'),
    _r('/panels_admin/update_comments', skip='POST only'),
    _r('/panels_admin/update_tags',     skip='POST only'),
    _r('/panels_admin/update_track',    skip='POST only'),
    _r('/panels_admin/create_badge',    skip='ajax'),
    _r('/panels_admin/link_badge',      skip='ajax'),
    _r('/panels_admin/validate_panel_app', skip='ajax'),
    _r('/panels_admin/validate_panelist', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /preregistration  (public — attendee self-service)
# ---------------------------------------------------------------------------
PREREGISTRATION = [
    _r('/preregistration/index',        auth='public', wait='form'),
    _r('/preregistration/kiosk',        auth='public', wait='h2'),
    _r('/preregistration/check_prereg', auth='public', wait='form'),
    _r('/preregistration/check_if_preregistered', auth='public', wait='form, h2'),
    _r('/preregistration/homepage',     auth='public', skip='requires login'),
    _r('/preregistration/form',         auth='public', skip='requires id'),
    _r('/preregistration/confirm',      auth='public', skip='requires id'),
    _r('/preregistration/repurchase',   auth='public', skip='requires id'),
    _r('/preregistration/resume_pending', auth='public', skip='requires id'),
    _r('/preregistration/group_members', auth='public', skip='requires id'),
    _r('/preregistration/group_payment', auth='public', skip='requires id'),
    _r('/preregistration/group_promo_codes', auth='public', skip='requires id'),
    _r('/preregistration/add_group_members', auth='public', skip='requires id'),
    _r('/preregistration/add_promo_codes', auth='public', skip='requires id'),
    _r('/preregistration/additional_info', auth='public', skip='requires id'),
    _r('/preregistration/badge_updated', auth='public', skip='requires id'),
    _r('/preregistration/claim_badge',  auth='public', skip='requires id'),
    _r('/preregistration/complete_badge_transfer', auth='public', skip='requires id'),
    _r('/preregistration/credit_card_retry', auth='public', skip='requires id'),
    _r('/preregistration/dealer_registration', auth='public', wait='form'),
    _r('/preregistration/dealer_confirmation', auth='public', skip='requires id'),
    _r('/preregistration/dealer_signed_document', auth='public', skip='requires id'),
    _r('/preregistration/finish_dealer_reg', auth='public', skip='requires id'),
    _r('/preregistration/new_badge_payment', auth='public', skip='requires id'),
    _r('/preregistration/not_found',    auth='public', wait='h2'),
    _r('/preregistration/paid_preregistrations', auth='public', skip='requires login'),
    _r('/preregistration/register_group_member', auth='public', skip='requires id'),
    _r('/preregistration/shirt_reorder', auth='public', skip='requires id'),
    _r('/preregistration/start_badge_transfer', auth='public', skip='requires id'),
    _r('/preregistration/transfer_badge', auth='public', skip='requires id'),
    _r('/preregistration/banned',       auth='public', wait='h2'),
    _r('/preregistration/invalid_badge', auth='public', wait='h2'),
    _r('/preregistration/at_door_confirmation', auth='public', skip='requires id'),
    _r('/preregistration/new_password_setup', auth='public', skip='requires token'),
    _r('/preregistration/reset_password', auth='public', wait='form'),
    _r('/preregistration/update_account', auth='public', skip='requires login'),
    _r('/preregistration/grant_account', auth='public', skip='requires id'),
    _r('/preregistration/reapply',      auth='public', skip='POST only'),
    _r('/preregistration/cancel_repurchase', auth='public', skip='POST only'),
    _r('/preregistration/defer_badge',  auth='public', skip='POST only'),
    _r('/preregistration/delete',       auth='public', skip='POST only'),
    _r('/preregistration/duplicate',    auth='public', skip='POST only'),
    _r('/preregistration/logout',       auth='public', skip='redirect only'),
    _r('/preregistration/abandon_badge', auth='public', skip='POST only'),
    _r('/preregistration/abandon_badges', auth='public', skip='POST only'),
    _r('/preregistration/cancel_dealer', auth='public', skip='POST only'),
    _r('/preregistration/process_free_prereg', auth='public', skip='POST only'),
    _r('/preregistration/post_dealer',  auth='public', skip='POST only'),
    _r('/preregistration/post_form',    auth='public', skip='POST only'),
    _r('/preregistration/unset_group_member', auth='public', skip='POST only'),
    _r('/preregistration/download_signnow_document', auth='public', skip='file export'),
    _r('/preregistration/email_promo_code', auth='public', skip='POST only'),
    _r('/preregistration/buy_own_group_badge', auth='public', skip='ajax'),
    _r('/preregistration/cancel_payment', auth='public', skip='ajax'),
    _r('/preregistration/cancel_payment_and_revert', auth='public', skip='ajax'),
    _r('/preregistration/cancel_prereg_payment', auth='public', skip='ajax'),
    _r('/preregistration/cancel_promo_code_payment', auth='public', skip='ajax'),
    _r('/preregistration/create_account', auth='public', skip='ajax'),
    _r('/preregistration/find_group_member', auth='public', skip='ajax'),
    _r('/preregistration/finish_pending_group_payment', auth='public', skip='ajax'),
    _r('/preregistration/finish_pending_payment', auth='public', skip='ajax'),
    _r('/preregistration/get_receipt_preview', auth='public', skip='ajax'),
    _r('/preregistration/login',        auth='public', skip='ajax'),
    _r('/preregistration/prereg_payment', auth='public', skip='ajax'),
    _r('/preregistration/process_attendee_payment', auth='public', skip='ajax'),
    _r('/preregistration/process_group_payment', auth='public', skip='ajax'),
    _r('/preregistration/purchase_upgrades', auth='public', skip='ajax'),
    _r('/preregistration/submit_authnet_charge', auth='public', skip='ajax'),
    _r('/preregistration/validate_account_email', auth='public', skip='ajax'),
    _r('/preregistration/validate_attendee', auth='public', skip='ajax'),
    _r('/preregistration/validate_badge_claim', auth='public', skip='ajax'),
    _r('/preregistration/validate_dealer', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /promo_codes
# ---------------------------------------------------------------------------
PROMO_CODES = [
    _r('/promo_codes/index',                wait='table, h2'),
    _r('/promo_codes/generate_promo_codes', wait='form'),
    _r('/promo_codes/delete_promo_codes',   skip='POST only'),
    _r('/promo_codes/update_promo_code',    skip='POST only'),
    _r('/promo_codes/export_promo_codes',   skip='file export'),
    _r('/promo_codes/add_promo_code_words', skip='ajax'),
    _r('/promo_codes/delete_all_promo_code_words', skip='ajax'),
    _r('/promo_codes/delete_promo_code_word', skip='ajax'),
    _r('/promo_codes/update_all',           skip='ajax'),
]

# ---------------------------------------------------------------------------
# /reg_admin
# ---------------------------------------------------------------------------
REG_ADMIN = [
    _r('/reg_admin/automated_transactions', wait='table, h2'),
    _r('/reg_admin/escalation_tickets',     wait='table, h2'),
    _r('/reg_admin/receipt_items',          wait='table, h2'),
    _r('/reg_admin/receipt_items_guide',    wait='h2'),
    _r('/reg_admin/attendee_accounts',      wait='table, h2'),
    _r('/reg_admin/attendee_account_form',  skip='requires id'),
    _r('/reg_admin/payment_pending_attendees', wait='table, h2'),
    _r('/reg_admin/orphaned_attendees',     wait='table, h2'),
    _r('/reg_admin/manage_workstations',    wait='table, h2'),
    _r('/reg_admin/close_out_terminals',    wait='h2'),
    _r('/reg_admin/confirm_import_attendees', wait='form, h2'),
    _r('/reg_admin/confirm_import_groups',  wait='form, h2'),
    _r('/reg_admin/import_attendees',       wait='form'),
    _r('/reg_admin/transfer_receipt',       skip='requires id'),
    _r('/reg_admin/edit_receipt_item',      skip='requires id'),
    _r('/reg_admin/cancel_multiple',        skip='POST only'),
    _r('/reg_admin/add_all_accounts',       skip='POST only'),
    _r('/reg_admin/add_multiple_accounts',  skip='POST only'),
    _r('/reg_admin/delete_attendee_account', skip='POST only'),
    _r('/reg_admin/delete_workstation',     skip='POST only'),
    _r('/reg_admin/attendee_search_export', skip='not_mappable'),
    _r('/reg_admin/close_receipt',          skip='not_mappable'),
    _r('/reg_admin/create_receipt',         skip='not_mappable'),
    _r('/reg_admin/move_to_active_receipt', skip='not_mappable'),
    _r('/reg_admin/process_full_refund',    skip='not_mappable'),
    _r('/reg_admin/remove_promo_code',      skip='not_mappable'),
    _r('/reg_admin/settle_up',              skip='not_mappable'),
    _r('/reg_admin/add_receipt_item',       skip='ajax'),
    _r('/reg_admin/add_receipt_txn',        skip='ajax'),
    _r('/reg_admin/cancel_receipt_txn',     skip='ajax'),
    _r('/reg_admin/comp_receipt_item',      skip='ajax'),
    _r('/reg_admin/comp_refund_receipt_item', skip='ajax'),
    _r('/reg_admin/delete_escalation_ticket', skip='ajax'),
    _r('/reg_admin/invalidate_badge',       skip='ajax'),
    _r('/reg_admin/refresh_model_receipt',  skip='ajax'),
    _r('/reg_admin/refresh_receipt_txn',    skip='ajax'),
    _r('/reg_admin/remove_receipt_item',    skip='ajax'),
    _r('/reg_admin/resend_receipt',         skip='ajax'),
    _r('/reg_admin/undo_receipt_item',      skip='ajax'),
    _r('/reg_admin/undo_refund_receipt_item', skip='ajax'),
    _r('/reg_admin/update_escalation_ticket', skip='ajax'),
    _r('/reg_admin/update_workstation',     skip='ajax'),
]

# ---------------------------------------------------------------------------
# /reg_reports
# ---------------------------------------------------------------------------
REG_REPORTS = [
    _r('/reg_reports/comped_badges',            wait='table, h2'),
    _r('/reg_reports/found_how',                wait='table, h2'),
    _r('/reg_reports/attendee_receipt_discrepancies', wait='table, h2'),
    _r('/reg_reports/attendees_nonzero_balance', wait='table, h2'),
    _r('/reg_reports/self_service_refunds',     wait='table, h2'),
    _r('/reg_reports/checkins_by_hour',         wait='table, h2'),
    _r('/reg_reports/checkins_by_admin_by_hour', skip='file export'),
    _r('/reg_reports/comped_badges_csv',        skip='file export'),
    _r('/reg_reports/checkins_by_hour_csv',     skip='file export'),
    _r('/reg_reports/self_service_refunds_csv', skip='file export'),
]

# ---------------------------------------------------------------------------
# /registration
# ---------------------------------------------------------------------------
REGISTRATION = [
    _r('/registration/index',               wait='form, h2'),
    _r('/registration/form',                skip='requires id'),
    _r('/registration/attendee_form',       skip='requires id'),
    _r('/registration/attendee_history',    skip='requires id'),
    _r('/registration/attendee_shifts',     skip='requires id'),
    _r('/registration/attendee_watchlist',  skip='requires id'),
    _r('/registration/attendee_data',       skip='requires id'),
    _r('/registration/check_in_form',       skip='requires id'),
    _r('/registration/check_in_group_form', skip='requires id'),
    _r('/registration/minor_check_form',    skip='requires id'),
    _r('/registration/complete_minor_check', skip='requires id'),
    _r('/registration/history',             skip='requires id'),
    _r('/registration/comments',            wait='table, h2'),
    _r('/registration/discount',            skip='requires id'),
    _r('/registration/lost_badge',          skip='requires id'),
    _r('/registration/shifts',              skip='requires id'),
    _r('/registration/pay',                 skip='requires id'),
    _r('/registration/new',                 wait='form'),
    _r('/registration/new_checkin',         wait='form, h2'),
    _r('/registration/pending_badges',      wait='table, h2'),
    _r('/registration/recent',              wait='table, h2'),
    _r('/registration/feed',                wait='table, h2'),
    _r('/registration/inactive',            wait='table, h2'),
    _r('/registration/staffers',            wait='table, h2'),
    _r('/registration/watchlist',           wait='table, h2'),
    _r('/registration/promo_code_groups',   wait='table, h2'),
    _r('/registration/promo_code_group_form', wait='form'),
    _r('/registration/stats',               wait='table, h2'),
    _r('/registration/reg_take_report',     wait='table, h2'),
    _r('/registration/review',              wait='table, h2'),
    _r('/registration/printed_name_problems', wait='table, h2'),
    _r('/registration/price',               wait='h2'),
    _r('/registration/arbitrary_charge_form', wait='form'),
    _r('/registration/check_txn_status',    wait='form, h2'),
    _r('/registration/qrcode_generator',    skip='binary'),
    _r('/registration/update_printers',     wait='form, h2'),
    _r('/registration/update_problem_names', skip='POST only'),
    _r('/registration/undo_badge_pickup',   skip='POST only'),
    _r('/registration/undo_checkin',        skip='POST only'),
    _r('/registration/undo_delete',         skip='POST only'),
    _r('/registration/undo_new_checkin',    skip='POST only'),
    _r('/registration/activate_badge',      skip='POST only'),
    _r('/registration/at_door_complete',    skip='POST only'),
    _r('/registration/delete',              skip='POST only'),
    _r('/registration/register',            skip='POST only'),
    _r('/registration/download_problem_names', skip='file export'),
    _r('/registration/shift_schedule_csv',  skip='file export'),
    _r('/registration/approve_badge',       skip='ajax'),
    _r('/registration/check_in',            skip='ajax'),
    _r('/registration/check_terminal_payment', skip='ajax'),
    _r('/registration/create_escalation_ticket', skip='ajax'),
    _r('/registration/delete_attendee',     skip='ajax'),
    _r('/registration/manual_reg_charge',   skip='ajax'),
    _r('/registration/mark_as_paid',        skip='ajax'),
    _r('/registration/poll_terminal_payment', skip='ajax'),
    _r('/registration/print_and_check_in_badges', skip='ajax'),
    _r('/registration/print_badge',         skip='ajax'),
    _r('/registration/remove_attendee_from_pickup_group', skip='ajax'),
    _r('/registration/remove_group_code',   skip='ajax'),
    _r('/registration/save_no_check_in',    skip='ajax'),
    _r('/registration/save_no_check_in_all', skip='ajax'),
    _r('/registration/set_reg_station',     skip='not_mappable'),
    _r('/registration/start_terminal_payment', skip='ajax'),
    _r('/registration/take_payment',        skip='ajax'),
    _r('/registration/update_attendee',     skip='ajax'),
    _r('/registration/validate_attendee',   skip='ajax'),
    _r('/registration/validate_attendee_checkin', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /saml  (public but internal)
# ---------------------------------------------------------------------------
SAML = [
    _r('/saml/acs',      auth='public', skip='not_mappable'),
    _r('/saml/metadata', auth='public', skip='not_mappable'),
]

# ---------------------------------------------------------------------------
# /schedule
# ---------------------------------------------------------------------------
SCHEDULE = [
    _r('/schedule/now',             wait='table, h2'),
    _r('/schedule/location',        wait='form, h2'),
    _r('/schedule/form',            wait='form, h2'),
    _r('/schedule/edit',            wait='h2'),
    _r('/schedule/event_panel_info', skip='file export'),
    _r('/schedule/panel_tech_needs', skip='file export'),
    _r('/schedule/panelists_owed_refunds', wait='table, h2'),
    _r('/schedule/delete',          skip='POST only'),
    _r('/schedule/delete_location', skip='POST only'),
    _r('/schedule/delete_location_cascade', skip='POST only'),
    _r('/schedule/ical',            skip='file export'),
    _r('/schedule/panels',          skip='file export'),
    _r('/schedule/time_ordered',    skip='file export'),
    _r('/schedule/xml',             skip='file export'),
    _r('/schedule/panels_json',     skip='ajax'),
    _r('/schedule/update_event',    skip='ajax'),
    _r('/schedule/validate_event',  skip='ajax'),
    _r('/schedule/validate_location', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /schedule_reports
# ---------------------------------------------------------------------------
SCHEDULE_REPORTS = [
    _r('/schedule_reports/index',               wait='table, h2'),
    _r('/schedule_reports/export_guidebook_xlsx', skip='file export'),
    _r('/schedule_reports/export_guidebook_zip', skip='file export'),
    _r('/schedule_reports/schedule_guidebook_xlsx', skip='file export'),
    _r('/schedule_reports/mark_item_synced',    skip='ajax'),
    _r('/schedule_reports/sync_all_items',      skip='ajax'),
]

# ---------------------------------------------------------------------------
# /security_admin
# ---------------------------------------------------------------------------
SECURITY_ADMIN = [
    _r('/security_admin/index',             wait='table, h2'),
    _r('/security_admin/watchlist_form',    wait='form'),
    _r('/security_admin/update_watchlist_entry', skip='ajax'),
    _r('/security_admin/validate_watchlist_entry', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /services  (public but a download endpoint)
# ---------------------------------------------------------------------------
SERVICES = [
    _r('/services/download_file', auth='public', skip='file export'),
]

# ---------------------------------------------------------------------------
# /shifts_admin
# ---------------------------------------------------------------------------
SHIFTS_ADMIN = [
    _r('/shifts_admin/index',           wait='form, h2'),
    _r('/shifts_admin/signups',         wait='table, h2'),
    _r('/shifts_admin/unfilled_shifts', wait='table, h2'),
    _r('/shifts_admin/staffers',        wait='table, h2'),
    _r('/shifts_admin/all_shifts',      wait='table, h2'),
    _r('/shifts_admin/staffers_by_job', wait='table, h2'),
    _r('/shifts_admin/summary',         wait='table, h2'),
    _r('/shifts_admin/form',            skip='requires id'),
    _r('/shifts_admin/template',        skip='requires id'),
    _r('/shifts_admin/assign_from_job', skip='requires id'),
    _r('/shifts_admin/unassign_from_job', skip='requires id'),
    _r('/shifts_admin/delete',          skip='POST only'),
    _r('/shifts_admin/delete_template', skip='POST only'),
    _r('/shifts_admin/delete_template_cascade', skip='POST only'),
    _r('/shifts_admin/goto_volunteer_checklist', skip='redirect only'),
    _r('/shifts_admin/shift_schedule_csv', skip='file export'),
    _r('/shifts_admin/unique_jobs_csv', skip='file export'),
    _r('/shifts_admin/assign',          skip='ajax'),
    _r('/shifts_admin/assign_shift',    skip='ajax'),
    _r('/shifts_admin/rate',            skip='ajax'),
    _r('/shifts_admin/set_worked',      skip='ajax'),
    _r('/shifts_admin/unassign',        skip='ajax'),
    _r('/shifts_admin/unassign_shift',  skip='ajax'),
    _r('/shifts_admin/update_shifts_info', skip='ajax'),
    _r('/shifts_admin/validate_job',    skip='ajax'),
    _r('/shifts_admin/validate_job_template', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /showcase  (public)
# ---------------------------------------------------------------------------
SHOWCASE = [
    _r('/showcase/index',           auth='public', wait='table, h2'),
    _r('/showcase/apply',           auth='public', wait='form'),
    _r('/showcase/studio',          auth='public', skip='requires id'),
    _r('/showcase/show_info',       auth='public', wait='h2'),
    _r('/showcase/confirm',         auth='public', skip='requires id'),
    _r('/showcase/view_image',      auth='public', skip='requires id'),
    _r('/showcase/developer',       auth='public', skip='POST only'),
    _r('/showcase/delete_developer', auth='public', skip='POST only'),
    _r('/showcase/mark_image',      auth='public', skip='POST only'),
    _r('/showcase/unmark_image',    auth='public', skip='POST only'),
    _r('/showcase/submit_game',     auth='public', skip='POST only'),
    _r('/showcase/validate_developer', auth='public', skip='ajax'),
    _r('/showcase/validate_new_studio', auth='public', skip='ajax'),
    _r('/showcase/validate_studio', auth='public', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /showcase_admin
# ---------------------------------------------------------------------------
SHOWCASE_ADMIN = [
    _r('/showcase_admin/index',         wait='table, h2'),
    _r('/showcase_admin/studios',       wait='table, h2'),
    _r('/showcase_admin/judges_owed_refunds', wait='table, h2'),
    _r('/showcase_admin/import_judges', wait='form'),
    _r('/showcase_admin/confirm_import_judges', wait='form, h2'),
    _r('/showcase_admin/assign',        skip='requires id'),
    _r('/showcase_admin/remove',        skip='POST only'),
    _r('/showcase_admin/reset_problems', skip='POST only'),
    _r('/showcase_admin/send_reviews',  skip='POST only'),
    _r('/showcase_admin/create_judge',  skip='POST only'),
    _r('/showcase_admin/disqualify_judge', skip='POST only'),
    _r('/showcase_admin/edit_game',     skip='POST only'),
    _r('/showcase_admin/edit_judge',    skip='POST only'),
    _r('/showcase_admin/mark_verdict',  skip='POST only'),
    _r('/showcase_admin/update_studio', skip='POST only'),
    _r('/showcase_admin/validate_game', skip='ajax'),
    _r('/showcase_admin/validate_judge', skip='ajax'),
    _r('/showcase_admin/validate_studio', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /showcase_judging
# ---------------------------------------------------------------------------
SHOWCASE_JUDGING = [
    _r('/showcase_judging/index',       wait='table, h2'),
    _r('/showcase_judging/game_review', skip='requires id'),
    _r('/showcase_judging/validate_judge', skip='ajax'),
    _r('/showcase_judging/validate_review', skip='ajax'),
]

# ---------------------------------------------------------------------------
# /staffing  (admin, but has its own auth flow)
# ---------------------------------------------------------------------------
STAFFING = [
    _r('/staffing/index',               wait='h2'),
    _r('/staffing/login',               wait='form, h2'),
    _r('/staffing/volunteer',           wait='h2'),
    _r('/staffing/printable',           wait='h2'),
    _r('/staffing/food_restrictions',   wait='form'),
    _r('/staffing/shirt_size',          wait='form'),
    _r('/staffing/volunteer_agreement', wait='h2'),
    _r('/staffing/emergency_procedures', wait='h2'),
    _r('/staffing/cash_handling',       wait='h2'),
    _r('/staffing/credits',             wait='h2'),
    _r('/staffing/hotel',               wait='form, h2'),
    _r('/staffing/jobs',                wait='table, h2'),
    _r('/staffing/shifts',              wait='table, h2'),
    _r('/staffing/onsite_jobs',         wait='table, h2'),
    _r('/staffing/onsite_sign_up',      wait='h2'),
    _r('/staffing/get_assigned_jobs',   skip='requires id'),
    _r('/staffing/get_available_jobs',  skip='requires id'),
    _r('/staffing/drop',                skip='ajax'),
    _r('/staffing/sign_up',             skip='ajax'),
    _r('/staffing/validate_food_restrictions', skip='ajax'),
    _r('/staffing/shifts_ical',         skip='file export'),
]

# ---------------------------------------------------------------------------
# /staffing_admin
# ---------------------------------------------------------------------------
STAFFING_ADMIN = [
    _r('/staffing_admin/pending_badges',    wait='table, h2'),
    _r('/staffing_admin/import_shifts',     wait='form'),
    _r('/staffing_admin/bulk_dept_import',  wait='form'),
    _r('/staffing_admin/lookup_departments', wait='table, h2'),
    _r('/staffing_admin/approve_badge',     skip='ajax'),
]

# ---------------------------------------------------------------------------
# /staffing_reports
# ---------------------------------------------------------------------------
STAFFING_REPORTS = [
    _r('/staffing_reports/index',           wait='h2'),
    _r('/staffing_reports/all_schedules',   wait='table, h2'),
    _r('/staffing_reports/departments',     wait='table, h2'),
    _r('/staffing_reports/ratings',         wait='table, h2'),
    _r('/staffing_reports/volunteer_hours_overview', wait='table, h2'),
    _r('/staffing_reports/volunteer_food',  wait='table, h2'),
    _r('/staffing_reports/restricted_untaken', wait='table, h2'),
    _r('/staffing_reports/consecutive_threshold', wait='table, h2'),
    _r('/staffing_reports/volunteer_checklists', wait='table, h2'),
    _r('/staffing_reports/name_in_credits', skip='file export'),
    _r('/staffing_reports/dept_head_contact_info', skip='file export'),
    _r('/staffing_reports/setup_teardown_neglect', wait='table, h2'),
    _r('/staffing_reports/volunteers_owed_refunds', wait='table, h2'),
    _r('/staffing_reports/volunteers_with_worked_hours', skip='file export'),
    _r('/staffing_reports/volunteer_checklist_csv', skip='file export'),
    _r('/staffing_reports/volunteers_owed_refunds_csv', skip='file export'),
]

# ---------------------------------------------------------------------------
# /statistics
# ---------------------------------------------------------------------------
STATISTICS = [
    _r('/statistics/index',         wait='table, h2'),
    _r('/statistics/badges_sold',   wait='table, h2'),
    _r('/statistics/map',           skip='requires feature: MAPS_ENABLED'),
    _r('/statistics/set_center',    skip='POST only'),
    _r('/statistics/refresh',       skip='ajax'),
    _r('/statistics/radial_zip_data', skip='ajax'),
    _r('/statistics/attendees_by_state', skip='file export'),
]

# ---------------------------------------------------------------------------
# /tabletop_checkins
# ---------------------------------------------------------------------------
TABLETOP_CHECKINS = [
    _r('/tabletop_checkins/index',          wait='form, h2'),
    _r('/tabletop_checkins/checkout_history', wait='table, h2'),
    _r('/tabletop_checkins/checkout_counts', skip='file export'),
    _r('/tabletop_checkins/add_game',       skip='ajax'),
    _r('/tabletop_checkins/checkout',       skip='ajax'),
    _r('/tabletop_checkins/return_to_owner', skip='ajax'),
    _r('/tabletop_checkins/returned',       skip='ajax'),
]

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
ROOT = [
    _r('/index',        wait='body'),
]


# ---------------------------------------------------------------------------
# Aggregated lists
# ---------------------------------------------------------------------------

ALL_ROUTE_GROUPS = [
    ACCOUNTS, API, ART_SHOW_ADMIN, ART_SHOW_APPLICATIONS, ART_SHOW_REPORTS,
    ATTRACTIONS, ATTRACTIONS_ADMIN, BADGE_EXPORTS, BADGE_PRINTING, BAND_ADMIN,
    BARCODE, BUDGET, DEALER_ADMIN, DEALER_REPORTS, DEPT_ADMIN, DEPT_CHECKLIST,
    DEVTOOLS, EMAIL_ADMIN, GROUP_ADMIN, GUEST_ADMIN, GUEST_REPORTS, GUESTS,
    HOTEL_LOTTERY, HOTEL_LOTTERY_ADMIN, HOTEL_REPORTS,
    INDIE_ARCADE, INDIE_ARCADE_REPORTS, INDIE_RETRO, INDIE_RETRO_REPORTS,
    LANDING, MARKETPLACE, MARKETPLACE_ADMIN, MERCH_ADMIN, MERCH_REPORTS,
    MITS, MITS_ADMIN, MIVS, MIVS_JUDGING, MIVS_REPORTS,
    OTHER_REPORTS, PANELS, PANELS_ADMIN, PREREGISTRATION, PROMO_CODES,
    REG_ADMIN, REG_REPORTS, REGISTRATION, SAML, SCHEDULE, SCHEDULE_REPORTS,
    SECURITY_ADMIN, SERVICES, SHIFTS_ADMIN, SHOWCASE, SHOWCASE_ADMIN,
    SHOWCASE_JUDGING, STAFFING, STAFFING_ADMIN, STAFFING_REPORTS,
    STATISTICS, TABLETOP_CHECKINS, ROOT,
]

ALL_ROUTES = [route for group in ALL_ROUTE_GROUPS for route in group]

PUBLIC_ROUTES = [r for r in ALL_ROUTES if r.auth == 'public' and not r.skip]
ADMIN_ROUTES  = [r for r in ALL_ROUTES if r.auth == 'admin'  and not r.skip]


# ---------------------------------------------------------------------------
# Data routes — require an existing database object.
# Query strings use Python format-string templates resolved at test time
# against the ``test_data`` fixture dict, e.g. ``'id={attendee_id}'``.
# These are NOT included in ALL_ROUTES; they are used by a separate
# ``test_data_route_visual`` parametrized test.
# ---------------------------------------------------------------------------

def _dr(path, query, auth='admin', wait=None):
    """Shorthand for a data route with a template query."""
    label = (path.lstrip('/') + '__' + query).replace('/', '__').replace('?', '_').replace('=', '_').replace('&', '_').replace('{', '').replace('}', '')
    return RouteSpec(path=path, label=label, auth=auth, skip=None, query=query, wait_selector=wait)


DATA_ROUTES = [
    # ---- registration ----
    _dr('/registration/form',             'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/attendee_form',    'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/attendee_data',    'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/attendee_history', 'id={attendee_id}',  wait='table, h2'),
    _dr('/registration/attendee_shifts',  'id={attendee_id}',  wait='table, h2'),
    _dr('/registration/shifts',           'id={attendee_id}',  wait='table, h2'),
    _dr('/registration/attendee_watchlist', 'id={attendee_id}', wait='h2'),
    _dr('/registration/check_in_form',    'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/history',          'id={attendee_id}',  wait='table, h2'),
    _dr('/registration/discount',         'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/lost_badge',       'id={attendee_id}',  wait='form, h2'),
    _dr('/registration/pay',              'id={attendee_id}',  wait='form, h2'),
    # ---- registration (group) ----
    _dr('/registration/check_in_group_form', 'id={group_id}', wait='form, h2'),
    # ---- group_admin ----
    _dr('/group_admin/history',           'id={group_id}',     wait='table, h2'),
    _dr('/group_admin/deletion_confirmation', 'id={group_id}', wait='form, h2'),
    # ---- dept_admin ----
    _dr('/dept_admin/role',               'id={dept_role_id}', wait='form, h2'),
    # ---- shifts_admin ----
    _dr('/shifts_admin/form',             'department_id={department_id}', wait='form, h2'),
    # ---- art_show_admin ----
    _dr('/art_show_admin/pieces',         'id={art_show_app_id}', wait='table, h2'),
    _dr('/art_show_admin/history',        'id={art_show_app_id}', wait='table, h2'),
    # ---- panels_admin ----
    _dr('/panels_admin/app',              'id={panel_app_id}', wait='form, h2'),
    # ---- mits_admin ----
    _dr('/mits_admin/team',               'id={mits_team_id}', wait='form, h2'),
    # ---- hotel_lottery_admin ----
    _dr('/hotel_lottery_admin/edit_hotel',         'id={lottery_hotel_id}',     wait='form, h2'),
    _dr('/hotel_lottery_admin/edit_room_type',     'id={lottery_room_type_id}', wait='form, h2'),
    _dr('/hotel_lottery_admin/edit_inventory_item', 'id={lottery_inventory_id}', wait='form, h2'),
    _dr('/hotel_lottery_admin/edit_partition',     'id={lottery_partition_id}', wait='form, h2'),
    _dr('/hotel_lottery_admin/lottery_run_detail', 'id={lottery_run_id}',       wait='table, h2'),
]
