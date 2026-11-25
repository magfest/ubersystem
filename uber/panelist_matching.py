"""Match panel applicants to existing badges for the panels admin Badges page.

Email is the first signal, because panelists enter names inconsistently. A group
often enters one email for every panelist, so an email match alone can point at
a family member's badge. Each candidate carries its match reason and any
differently named panelist already linked to it; the Link and Add New Badge
handlers ask for confirmation from these.
"""
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, or_

from uber.models import Attendee, PanelApplicant

MATCH_EMAIL_AND_NAME = 'email and name'
MATCH_EMAIL = 'email only'
MATCH_NAME = 'name only'
_REASON_ORDER = [MATCH_EMAIL_AND_NAME, MATCH_EMAIL, MATCH_NAME]


def _norm(value):
    return (value or '').strip().lower()


def names_match(first_a, last_a, first_b, last_b):
    """Return True when last names are equal and one first name starts with the other.

    The prefix rule accepts Jim for Jimmy; it does not accept Bob for Robert.
    """
    first_a, first_b, last_a, last_b = _norm(first_a), _norm(first_b), _norm(last_a), _norm(last_b)
    if not (first_a and first_b and last_a and last_a == last_b):
        return False
    return first_a.startswith(first_b) or first_b.startswith(first_a)


@dataclass
class BadgeCandidate:
    attendee: Attendee
    reason: str
    conflict: PanelApplicant | None = None
    conflict_same_panel: bool = False


def _pick_conflict(applicant, linked_rows):
    """Return the first linked row with another person's name, preferring one on the applicant's panels."""
    app_ids = {app.id for app in applicant.applications}
    others = [row for row in linked_rows if row.id != applicant.id
              and not names_match(row.first_name, row.last_name, applicant.first_name, applicant.last_name)]
    for row in others:
        if app_ids & {app.id for app in row.applications}:
            return row, True
    return (others[0], False) if others else (None, False)


def find_conflict(session, applicant, attendee):
    """Return the differently named applicant row already linked to this badge, and whether it shares a panel."""
    rows = session.query(PanelApplicant).filter(PanelApplicant.attendee_id == attendee.id).all()
    return _pick_conflict(applicant, rows)


def candidates_by_applicant(session, applicants):
    """Return {applicant id: candidates} for many panelists using one badge query and one linked-row query.

    Candidates are valid badges matching by email or name, strongest first and flagged last. The Badges
    page lists every unlinked panelist, so a query per panelist would scan the attendee table hundreds of times.
    """
    emails = {_norm(a.email) for a in applicants} - {''}
    last_names = {_norm(a.last_name) for a in applicants} - {''}
    clauses = []
    if emails:
        clauses.append(func.lower(func.trim(Attendee.email)).in_(emails))
    if last_names:
        clauses.append(func.lower(func.trim(Attendee.last_name)).in_(last_names))
    pool = []
    if clauses:
        pool = session.query(Attendee).filter(Attendee.is_valid == True, or_(*clauses)).all()  # noqa: E712

    by_email, by_last_name, linked = defaultdict(list), defaultdict(list), defaultdict(list)
    for attendee in pool:
        by_email[_norm(attendee.email)].append(attendee)
        by_last_name[_norm(attendee.last_name)].append(attendee)
    if pool:
        for row in session.query(PanelApplicant).filter(PanelApplicant.attendee_id.in_([a.id for a in pool])):
            linked[row.attendee_id].append(row)

    result = {}
    for applicant in applicants:
        email, last_name = _norm(applicant.email), _norm(applicant.last_name)
        matched = (by_email[email] if email else []) + (by_last_name[last_name] if last_name else [])
        possible = {a.id: a for a in matched}
        candidates = []
        for attendee in possible.values():
            email_match = bool(email) and _norm(attendee.email) == email
            name_match = names_match(attendee.first_name, attendee.last_name, applicant.first_name, applicant.last_name)
            if email_match and name_match:
                reason = MATCH_EMAIL_AND_NAME
            elif email_match:
                reason = MATCH_EMAIL
            elif name_match:
                reason = MATCH_NAME
            else:
                continue
            conflict, same_panel = _pick_conflict(applicant, linked[attendee.id])
            candidates.append(BadgeCandidate(attendee, reason, conflict, same_panel))
        result[applicant.id] = sorted(candidates, key=lambda cand: (
            cand.conflict is not None, _REASON_ORDER.index(cand.reason), cand.attendee.full_name))
    return result


def badge_candidates(session, applicant):
    """Return one panelist's candidates; see candidates_by_applicant."""
    return candidates_by_applicant(session, [applicant])[applicant.id]


def link_confirm_message(applicant, attendee, conflict, same_panel):
    if same_panel:
        where = 'this panel'
    elif conflict.applications:
        where = f'"{conflict.applications[0].name}"'
    else:
        where = 'another panel'
    return (f'{attendee.full_name} ({attendee.badge}) is already linked to panelist {conflict.full_name} on {where}. '
            f'Link {applicant.full_name} to this badge anyway?')


def create_confirm_message(applicant, candidate):
    attendee = candidate.attendee
    return (f'{attendee.full_name} ({attendee.badge}) may already be this panelist (matches {candidate.reason}). '
            f'Create a new badge for {applicant.full_name} anyway?')
