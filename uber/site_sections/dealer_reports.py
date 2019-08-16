from uber.config import c
from uber.decorators import all_renderable, csv_file, xlsx_file
from uber.models import Group


@all_renderable(c.STATS)
class Root:
    @csv_file
    def seller_table_info(self, out, session):
        out.writerow([
            'Business Name',
            'Table Name',
            'Description',
            'URL',
            'Point of Contact',
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
        dealer_groups = session.query(Group).filter(Group.tables > 0).all()
        for group in dealer_groups:
            if group.approved and group.is_dealer:
                full_name = group.leader.full_name if group.leader else ''
                out.writerow([
                    group.name,
                    full_name,
                    group.description,
                    group.website,
                    group.leader.legal_name or group.leader.full_name,
                    group.leader.email,
                    group.leader.cellphone,
                    group.address1,
                    group.address2,
                    group.city,
                    group.region,
                    group.zip_code,
                    group.country,
                    group.tables,
                    group.amount_paid,
                    group.cost,
                    group.badges
                ])

    @xlsx_file
    def seller_comptroller_info(self, out, session):
        dealer_groups = session.query(Group).filter(Group.tables > 0).all()
        rows = []
        for group in dealer_groups:
            if group.approved and group.is_dealer:
                rows.append([
                    group.name,
                    group.leader.email,
                    group.leader.legal_name or group.leader.full_name,
                    group.leader.cellphone,
                    group.physical_address
                ])
        header_row = [
            'Vendor Name',
            'Contact Email',
            'Primary Contact',
            'Contact Phone #',
            'Physical Address']
        out.writerows(header_row, rows)