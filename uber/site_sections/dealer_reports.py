from sqlalchemy import or_, and_

from uber.config import c
from uber.decorators import all_renderable, csv_file, xlsx_file, log_pageview
from uber.models import Group, ModelReceipt
from uber.utils import extract_urls


@all_renderable()
class Root:
    @log_pageview
    def dealer_receipt_discrepancies(self, session, only_dealers=False):
        if only_dealers:
            filters = [Group.is_dealer == True, Group.status.in_([c.APPROVED, c.SHARED])]  # noqa: E712
        else:
            filters = [or_(Group.is_dealer == False, Group.status.in_([c.APPROVED, c.SHARED]))]

        groups = session.query(Group).filter(*filters).join(Group.active_receipt).outerjoin(
            ModelReceipt.receipt_items).group_by(ModelReceipt.id).group_by(Group.id).having(
                Group.cost_cents != ModelReceipt.fkless_item_total_sql)

        return {
            'groups': groups,
            'only_dealers': only_dealers,
        }

    @log_pageview
    def dealers_nonzero_balance(self, session, include_no_receipts=False, include_discrepancies=False):
        item_subquery = session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                                      ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()
        
        if include_discrepancies:
            filter = True
        else:
            filter = Group.cost_cents == item_subquery.c.item_total

        groups_and_totals = session.query(
            Group, ModelReceipt.payment_total_sql, ModelReceipt.refund_total_sql, item_subquery.c.item_total
            ).filter(Group.is_valid == True).join(Group.active_receipt).outerjoin(
                ModelReceipt.receipt_txns).join(item_subquery, Group.id == item_subquery.c.owner_id).group_by(
                    ModelReceipt.id).group_by(Group.id).group_by(item_subquery.c.item_total).having(
                        and_((ModelReceipt.payment_total_sql - ModelReceipt.refund_total_sql) != item_subquery.c.item_total,
                             filter))
        
        if include_no_receipts:
            groups_no_receipts = session.query(Group).outerjoin(ModelReceipt,
                                                                Group.active_receipt).filter(Group.cost > 0,
                                                                                             ModelReceipt.id == None)
        else:
            groups_no_receipts = []
        
        return {
            'groups_and_totals': groups_and_totals,
            'include_discrepancies': include_discrepancies,
            'groups_no_receipts': groups_no_receipts,
        }

    @csv_file
    def seller_initial_review(self, out, session):
        out.writerow([
            'Group ID',
            'Group Leader\'s Name',
            'Table Name',
            'Website URL',
            'What They Sell'
        ])

        dealer_groups = session.query(Group).filter(Group.tables > 0).all()
        for group in dealer_groups:
            full_name = group.leader.full_name if group.leader else ''
            out.writerow([
                group.id,
                full_name,
                group.name,
                group.website,
                group.wares
            ])

    @csv_file
    def approved_seller_table_info(self, out, session):
        out.writerow([
            'Table Name',
            'Description',
            'URL',
            'Seller Name',
            'Seller Legal Name',
            'Email',
            'Phone Number',
            'Address1',
            'Address2',
            'City',
            'State/Region',
            'Zip Code',
            'Country',
            'Tables',
            'Amount Paid',
            'Cost',
            'Badges'
        ])
        dealer_groups = session.query(Group).filter(Group.is_dealer == True).all()  # noqa: E712
        for group in dealer_groups:
            if group.status in [c.APPROVED, c.SHARED]:
                full_name = group.leader.full_name if group.leader else ''
                out.writerow([
                    group.name,
                    group.description,
                    group.website,
                    full_name,
                    group.leader.legal_name if group.leader else '',
                    group.email,
                    group.phone if group.phone else group.leader.cellphone,
                    group.address1,
                    group.address2,
                    group.city,
                    group.region,
                    str(group.zip_code),
                    group.country,
                    group.tables,
                    group.amount_paid / 100,
                    group.cost,
                    group.badges
                ])

    @xlsx_file
    def all_sellers_application_info(self, out, session):
        out.writerow([
            'Table Name',
            'Description',
            'Seller Name',
            'Email',
            'Tables',
            'Badges',
            'Website',
            'What they sell',
            'Categories',
            'Other Category',
            'Special Requests',
            ])

        dealer_groups = session.query(Group).filter(Group.is_dealer == True).all()  # noqa: E712

        def write_url_or_text(cell, is_url=False, last_cell=False):
            if is_url:
                url = cell if cell.startswith('http') else 'http://' + cell
                out.writecell(cell, url=url, last_cell=last_cell)
            else:
                out.writecell(cell, format={'text_wrap': True}, last_cell=last_cell)

        for group in dealer_groups:
            wares_urls = extract_urls(group.wares) or []
            full_name = group.leader.full_name if group.leader else ''

            row = [
                group.name,
                group.description,
                full_name,
                group.email,
                group.tables,
                group.badges,
                group.website,
                group.wares,
                " / ".join(group.categories_labels),
                group.categories_text,
                group.special_needs,
            ] + wares_urls

            for cell in row[:-1]:
                write_url_or_text(cell, cell == group.website or cell in wares_urls)

            final_cell = row[-1:][0]
            write_url_or_text(final_cell, final_cell == group.website or final_cell in wares_urls, last_cell=True)

    @xlsx_file
    def seller_comptroller_info(self, out, session):
        dealer_groups = session.query(Group).filter(Group.tables > 0).all()
        rows = []
        for group in dealer_groups:
            if group.status in [c.APPROVED, c.SHARED] and group.is_dealer:
                rows.append([
                    group.name,
                    group.email,
                    group.leader.legal_name or group.leader.full_name,
                    group.phone if group.phone else group.leader.cellphone,
                    group.address1,
                    group.address2,
                    group.city,
                    group.region,
                    str(group.zip_code),
                    group.country,
                    group.has_permit,
                    group.license
                ])
        header_row = [
            'Vendor Name',
            'Contact Email',
            'Primary Contact',
            'Contact Phone #',
            'Address 1',
            'Address 2',
            'City',
            'State/Region',
            'Zip Code',
            'Country',
            'Has Permit',
            'License #']
        out.writerows(header_row, rows)

    @xlsx_file
    def seller_applications(self, out, session):
        dealer_groups = session.query(Group).filter(Group.is_dealer).all()

        header_row = [
            'id',
            'name',
            'registered',
            '']
        out.writerow(header_row)

        for group in dealer_groups:
            out.writecell(group.id)
            out.writecell(group.name)
            out.writecell(group.registered.replace(tzinfo=None), format={'num_format': 'dd/mm/yy hh:mm'})
            out.writecell(group.name, url="{}/group_admin/form?id={}".format(c.URL_BASE, group.id), last_cell=True)

    @xlsx_file
    def waitlisted_group_info(self, out, session):
        waitlisted_groups = session.query(Group).filter(Group.status == c.WAITLISTED).all()
        rows = []
        for group in waitlisted_groups:
            if group.is_dealer:
                rows.append([
                    group.name,
                    group.leader.full_name,
                    group.email,
                    group.website,
                    group.physical_address
                ])
        header_row = [
            'Group Name',
            'Group Leader Name',
            'Group Leader Email',
            'Website',
            ]
        out.writerows(header_row, rows)

    @xlsx_file
    def seller_tax_info(self, out, session):
        approved_groups = session.query(Group).filter(Group.status.in_([c.APPROVED, c.SHARED])).all()
        rows = []
        for group in approved_groups:
            if group.is_dealer:
                rows.append([
                    group.name,
                    group.leader.full_name,
                    group.email,
                    group.physical_address,
                    group.phone if group.phone else group.leader.cellphone,
                    group.special_needs,
                    group.admin_notes,
                    group.wares,
                ])
        header_row = [
            'Business Name',
            'Group Leader Name',
            'Group Leader Email',
            'Business Address',
            'Business Phone Number',
            'Special Requests',
            'Admin Notes',
            'What They Sell',
            ]
        out.writerows(header_row, rows)
