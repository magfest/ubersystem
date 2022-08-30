from collections import defaultdict

from uber.config import c
from uber.models import AttendeeAccount, Group, initialize_db, Session, SignedDocument

dealers_to_keep = []
dealers_to_cancel = []
cancelled_doc_ids = []

initialize_db()
session = Session().session

try:
    cancel_dealer_list = open("dealers_to_cancel.txt", 'r+')
    dealers_to_cancel = cancel_dealer_list.read().split(',')
    cancel_dealer_list.close()
except FileNotFoundError:
    try:
        dealer_list = open("dealers_to_keep.txt", 'r+')
        dealers_to_keep = dealer_list.read().split(',')
        dealer_list.close()
    except FileNotFoundError:
        dealer_list = open("dealers_to_keep.txt", 'w+')
        for account in session.query(AttendeeAccount):
            latest_signed, latest_unsigned = None, None
            sorted_valid_dealer_groups = sorted([attendee.group for attendee in account.valid_group_badges if attendee.group and attendee.is_group_leader and attendee.group.is_dealer and attendee.group.status == c.UNAPPROVED], key=lambda g: g.registered)
            if sorted_valid_dealer_groups:
                groups_by_name = defaultdict(lambda: {'latest_signed': '', 'latest_unsigned': ''})
                for group in sorted_valid_dealer_groups:
                    if group.signnow_document_signed:
                        groups_by_name[group.name]['latest_signed'] = group
                    else:
                        groups_by_name[group.name]['latest_unsigned'] = group
                
                for group_name in groups_by_name:
                    if groups_by_name[group_name]['latest_signed']:
                        dealers_to_keep.append(groups_by_name[group_name]['latest_signed'].id)
                    else:
                        dealers_to_keep.append(groups_by_name[group_name]['latest_unsigned'].id)
        dealer_list.write(",".join(dealers_to_keep))
        dealer_list.close()

if dealers_to_keep:
    cancelled_doc_ids = []
    for group in session.query(Group).filter(Group.status.in_([c.UNAPPROVED, c.WAITLISTED]), Group.tables > 0):
        if group.id not in dealers_to_keep:
            document = session.query(SignedDocument).filter_by(model="Group", fk_id=group.id).first()
            if document:
                cancelled_doc_ids.append(document.document_id)
            group.status = c.CANCELLED
            group.admin_notes = "Automated: Cancelled as part of the Great Dealer Purge of 2022."
        session.add(group)
        session.commit()
    doc_id_list = open("docs_to_cancel.txt", 'w+')
    doc_id_list.write(",".join(cancelled_doc_ids))
    doc_id_list.close()

if dealers_to_cancel:
    for group in session.query(Group).filter(Group.id.in_(dealers_to_cancel)):
        document = session.query(SignedDocument).filter_by(model="Group", fk_id=group.id).first()
        if document:
            cancelled_doc_ids.append(document.document_id)
        group.status = c.CANCELLED
        group.admin_notes = "Automated: Cancelled as part of the Great Dealer Purge of 2022 (Manual Purge)."
        session.add(group)
        session.commit()

    doc_id_list = open("docs_to_cancel_manual.txt", 'w+')
    doc_id_list.write(",".join(cancelled_doc_ids))
    doc_id_list.close()