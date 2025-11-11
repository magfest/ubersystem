from uber.config import c
from uber.decorators import all_renderable, csv_file, log_pageview

from collections import defaultdict
from sqlalchemy import or_, and_

from uber.custom_tags import format_currency
from uber.models import ArtShowApplication, ArtShowBidder, ArtShowPiece, ArtShowReceipt, Attendee, ModelReceipt
from uber.utils import localized_now


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
        }

    def sales_invoices(self, session, message='', start=1, end=''):
        receipts = []
        try:
            start = int(start)
        except Exception:
            message = "Starting invoice number must be an integer."
        if end:
            try:
                end = int(end)
            except Exception:
                message = "Ending invoice number must be an integer or blank."

        if not message:
            filters = [ArtShowReceipt.invoice_num >= start, ArtShowReceipt.closed != None]  # noqa: E711
            if end:
                filters.append(ArtShowReceipt.invoice_num <= end)

            receipts = session.query(ArtShowReceipt).join(ArtShowReceipt.attendee)\
                .filter(*filters).order_by(ArtShowReceipt.closed.desc()).all()
            if not receipts:
                message = "No invoices found!"

        return {
            'message': message,
            'receipts': receipts,
            'start': start,
            'end': end,
        }

    def artist_invoices(self, session, message=''):
        apps = session.query(ArtShowApplication).join(ArtShowApplication.art_show_pieces)\
            .filter(ArtShowApplication.art_show_pieces.any(ArtShowPiece.status.in_([c.SOLD, c.PAID]))).all()
        if not apps:
            message = "No invoices found!"

        return {
            'message': message,
            'apps': apps,
        }

    def high_bids(self, session, message='', admin_report=None):
        return {
            'message': message,
            'won_pieces': session.query(ArtShowPiece).join(ArtShowPiece.buyer).join(
                Attendee.art_show_bidder).filter(ArtShowPiece.winning_bid.isnot(None), ArtShowPiece.status == c.SOLD
                                                 ).order_by(ArtShowBidder.bidder_num, ArtShowPiece.piece_id,
                                                            ArtShowPiece.name),
            'admin_report': admin_report,
            'now': localized_now(),
        }

    def pieces_by_status(self, session, message='', **params):
        filters = []
        if 'yes_status' in params:
            try:
                yes_status = [int(params['yes_status'])]
            except Exception:
                yes_status = list(params['yes_status'])
            filters.append(ArtShowApplication.art_show_pieces.any(ArtShowPiece.status.in_(yes_status)))
        if 'no_status' in params:
            try:
                no_status = [int(params['no_status'])]
            except Exception:
                no_status = list(params['no_status'])
            filters.append(ArtShowApplication.art_show_pieces.any(~ArtShowPiece.status.in_(no_status)))

        apps = session.query(ArtShowApplication).join(ArtShowApplication.art_show_pieces).filter(*filters).all()

        if not apps:
            message = 'No pieces found!'
        return {
            'message': message,
            'apps': apps,
            'yes_status': yes_status if 'yes_status' in params else None,
            'no_status': no_status if 'no_status' in params else None,
        }

    def summary(self, session, message=''):
        general_pieces = session.query(ArtShowPiece).join(ArtShowApplication).filter(
            ArtShowApplication.status == c.APPROVED, ArtShowPiece.gallery == c.GENERAL)
        mature_pieces = session.query(ArtShowPiece).join(ArtShowApplication).filter(
            ArtShowApplication.status == c.APPROVED, ArtShowPiece.gallery == c.MATURE)

        general_auctioned = general_pieces.filter(ArtShowPiece.voice_auctioned == True)  # noqa: E712
        mature_auctioned = mature_pieces.filter(ArtShowPiece.voice_auctioned == True)  # noqa: E712

        general_sold = general_pieces.filter(ArtShowPiece.status.in_([c.SOLD, c.PAID]))
        mature_sold = mature_pieces.filter(ArtShowPiece.status.in_([c.SOLD, c.PAID]))

        artists_with_pieces = session.query(ArtShowApplication).filter(
            ArtShowApplication.art_show_pieces != None, ArtShowApplication.status == c.APPROVED)  # noqa: E711

        approved_apps = session.query(ArtShowApplication).filter(ArtShowApplication.status == c.APPROVED)

        panels, tables = {}, {}
        for key in 'general', 'mature', 'fee':
            panels[key] = defaultdict(int)
            tables[key] = defaultdict(int)

        for app in approved_apps:
            if app.overridden_price == 0:
                panels['general']['free'] += app.panels
                panels['mature']['free'] += app.panels_ad
                tables['general']['free'] += app.tables
                tables['mature']['free'] += app.tables_ad
            else:
                panels['general']['paid'] += app.panels
                panels['mature']['paid'] += app.panels_ad
                tables['general']['paid'] += app.tables
                tables['mature']['paid'] += app.tables_ad
                
                panels['fee']['general'] += app.panels * c.COST_PER_PANEL
                panels['fee']['mature'] += app.panels_ad * c.COST_PER_PANEL
                tables['fee']['general'] += app.tables * c.COST_PER_TABLE
                tables['fee']['mature'] += app.tables_ad * c.COST_PER_TABLE

        return {
            'message': message,
            'general_sales_sum': sum([piece.sale_price for piece in general_sold]),
            'mature_sales_sum': sum([piece.sale_price for piece in mature_sold]),
            'general_count': general_pieces.count(),
            'mature_count': mature_pieces.count(),
            'general_sold_count': general_sold.count(),
            'mature_sold_count': mature_sold.count(),
            'general_auctioned_count': general_auctioned.count(),
            'mature_auctioned_count': mature_auctioned.count(),
            'artist_count': artists_with_pieces.count(),
            'panels': panels,
            'total_panels': sum([count for key, count in panels['general'].items()]) + sum(
                [count for key, count in panels['mature'].items()]),
            'tables': tables,
            'total_tables': sum([count for key, count in tables['general'].items()]) + sum(
                [count for key, count in tables['mature'].items()]),
            'now': localized_now(),
        }

    def auction_report(self, session, message='', mature=None):
        filters = [ArtShowPiece.status == c.VOICE_AUCTION]

        if mature:
            filters.append(ArtShowPiece.gallery == c.MATURE)
        else:
            filters.append(ArtShowPiece.gallery == c.GENERAL)

        return {
            'message': message,
            'pieces': session.query(ArtShowPiece).filter(*filters).join(ArtShowPiece.app).all(),
            'mature': mature,
            'now': localized_now(),
        }

    @log_pageview
    def artist_receipt_discrepancies(self, session):
        apps = session.query(ArtShowApplication).filter(
            ArtShowApplication.status == c.APPROVED
            ).join(ArtShowApplication.active_receipt).outerjoin(ModelReceipt.receipt_items).group_by(
                ModelReceipt.id).group_by(ArtShowApplication.id).having(
                    ArtShowApplication.true_default_cost_cents != ModelReceipt.fkless_item_total_sql)

        return {
            'apps': apps,
        }

    @log_pageview
    def artists_nonzero_balance(self, session, include_no_receipts=False, include_discrepancies=False):
        item_subquery = session.query(ModelReceipt.owner_id, ModelReceipt.item_total_sql.label('item_total')
                                      ).join(ModelReceipt.receipt_items).group_by(ModelReceipt.owner_id).subquery()

        if include_discrepancies:
            filter = True
        else:
            filter = ArtShowApplication.true_default_cost_cents == item_subquery.c.item_total

        apps_and_totals = session.query(
            ArtShowApplication, ModelReceipt.payment_total_sql, ModelReceipt.refund_total_sql, item_subquery.c.item_total
            ).filter(ArtShowApplication.status == c.APPROVED).join(ArtShowApplication.active_receipt).outerjoin(
                ModelReceipt.receipt_txns).join(item_subquery, ArtShowApplication.id == item_subquery.c.owner_id).group_by(
                    ModelReceipt.id).group_by(ArtShowApplication.id).group_by(item_subquery.c.item_total).having(
                        and_((ModelReceipt.payment_total_sql - ModelReceipt.refund_total_sql) != item_subquery.c.item_total,
                             filter))

        if include_no_receipts:
            apps_no_receipts = session.query(ArtShowApplication).outerjoin(
                ModelReceipt, ArtShowApplication.active_receipt).filter(ArtShowApplication.true_default_cost > 0,
                                                                        ModelReceipt.id == None)
        else:
            apps_no_receipts = []

        return {
            'apps_and_totals': apps_and_totals,
            'include_discrepancies': include_discrepancies,
            'apps_no_receipts': apps_no_receipts,
        }

    @csv_file
    def banner_csv(self, out, session):
        out.writerow(['Banner Name', 'Locations'])
        for app in session.query(ArtShowApplication).filter(ArtShowApplication.status != c.DECLINED):
            out.writerow([app.display_name, app.locations])

    @csv_file
    def approved_international_artists(self, out, session):
        out.writerow(['Artist\'s Name',
                      'Legal Name',
                      'Name on Check',
                      'Email',
                      'Agent Name',
                      'Agent Email',
                      ])

        for app in session.query(ArtShowApplication
                                 ).join(Attendee, ArtShowApplication.attendee_id == Attendee.id
                                        ).filter(ArtShowApplication.status == c.APPROVED,
                                                 or_(and_(ArtShowApplication.country != '',
                                                          ArtShowApplication.country != 'United States'),
                                                     and_(Attendee.country != '',
                                                          Attendee.country != 'United States'))):
            out.writerow([app.artist_name or app.attendee.full_name,
                          app.attendee.legal_first_name + " " + app.attendee.legal_last_name,
                          app.check_payable or (app.attendee.legal_first_name + " " + app.attendee.legal_last_name),
                          app.email,
                          app.single_agent.full_name if app.current_agents else '',
                          app.single_agent.email if app.current_agents else '',
                          ])

    @csv_file
    def artist_csv(self, out, session):
        out.writerow(['Application Status',
                      'Paid?',
                      'Artist Name',
                      'Full Name',
                      'Art Delivery',
                      'General Panels',
                      'General Tables',
                      'Mature Panels',
                      'Mature Tables',
                      'Description',
                      'Website URL',
                      'Special Requests',
                      'Discounted Price',
                      'Admin Notes',
                      'Banner Name',
                      'Piece Count Total',
                      'Badge Status',
                      'Badge Name',
                      'Email',
                      'Phone',
                      'Address 1',
                      'Address 2',
                      'City',
                      'Region',
                      'Postal Code',
                      'Country',
                      ])

        for app in session.query(ArtShowApplication):
            if app.amount_unpaid == 0:
                paid = "Yes"
            elif app.status == c.APPROVED:
                paid = "No"
            else:
                paid = "N/A"

            if app.address1 or not app.attendee:
                address_model = app
            else:
                address_model = app.attendee

            out.writerow([app.status_label,
                          paid,
                          app.artist_name,
                          app.attendee.full_name if app.attendee else 'N/A',
                          app.delivery_method_label,
                          app.panels,
                          app.tables,
                          app.panels_ad,
                          app.tables_ad,
                          app.description,
                          app.website,
                          app.special_needs,
                          app.overridden_price,
                          app.admin_notes,
                          app.display_name,
                          len(app.art_show_pieces),
                          app.attendee.badge_status_label if app.attendee else 'N/A',
                          app.attendee.badge_printed_name if app.attendee else 'N/A',
                          app.attendee.email if app.attendee else 'N/A',
                          app.attendee.cellphone if app.attendee else 'N/A',
                          address_model.address1,
                          address_model.address2,
                          address_model.city,
                          address_model.region,
                          address_model.zip_code,
                          address_model.country,
                          ])

    @csv_file
    def pieces_csv(self, out, session):
        out.writerow(["Artist Name",
                      "Artist Code",
                      "Piece ID",
                      "Piece Name",
                      "Status",
                      "Type",
                      "Media",
                      "Minimum Bid",
                      c.QS_PRICE_TERM,
                      "Sale Price",
                      ])

        for piece in session.query(ArtShowPiece):
            if piece.type == c.PRINT:
                piece_type = "{} ({} of {})".format(piece.type_label, piece.print_run_num, piece.print_run_total)
            else:
                piece_type = piece.type_label
            
            artist_code, piece_id = piece.artist_and_piece_id.split('-')

            out.writerow([piece.app_display_name,
                          artist_code,
                          piece_id,
                          piece.name,
                          piece.status_label,
                          piece_type,
                          piece.media,
                          '$' + str(piece.opening_bid) if piece.valid_for_sale else 'N/A',
                          '$' + str(piece.quick_sale_price) if piece.valid_quick_sale else 'N/A',
                          '$' + str(piece.sale_price) if piece.status in [c.SOLD, c.PAID] else 'N/A',
                          ])

    @csv_file
    def unpicked_up_pieces(self, out, session):
        out.writerow(["Piece ID",
                      "Artist Locations",
                      "Artist Name",
                      "Gallery",
                      "Winning Bid",
                      "Winning Bidder #",
                      "Winner Badge Name",
                      "Winner Legal Name",
                      "Winner Phone #",
                      "Winner Email"])

        for piece in session.query(ArtShowPiece).join(ArtShowBidder).filter(ArtShowPiece.status == c.SOLD
                                                                            ).order_by(ArtShowBidder.bidder_num):
            current_row = [piece.app.artist_id + "-" + str(piece.piece_id),
                           piece.app.locations,
                           piece.app.artist_name or piece.app.attendee.full_name,
                           piece.gallery_label,
                           format_currency(piece.winning_bid),
                           piece.winning_bidder.bidder_num]

            winning_attendee = piece.winning_bidder.attendee
            if winning_attendee:
                current_row.extend([winning_attendee.badge_printed_name,
                                    winning_attendee.legal_first_name + " " + winning_attendee.legal_last_name,
                                    winning_attendee.cellphone,
                                    winning_attendee.email])
            out.writerow(current_row)

    @csv_file
    def bidder_csv(self, out, session):
        out.writerow(["Signed Up",
                      "Bidder Number",
                      "Full Name",
                      "Badge Name",
                      "Email Address",
                      "Address 1",
                      "Address 2",
                      "City",
                      "Region",
                      "Postal Code",
                      "Country",
                      "Phone",
                      "Admin Notes",
                      "Email Bids?",
                      ])

        for bidder in session.query(ArtShowBidder).join(ArtShowBidder.attendee):
            if bidder.attendee.badge_status == c.NOT_ATTENDING and bidder.attendee.art_show_applications:
                address_model = bidder.attendee.art_show_applications[0]
            else:
                address_model = bidder.attendee

            out.writerow([bidder.signed_up_local,
                          bidder.bidder_num,
                          bidder.attendee.full_name,
                          bidder.attendee.badge_printed_name,
                          bidder.attendee.email,
                          address_model.address1,
                          address_model.address2,
                          address_model.city,
                          address_model.region,
                          address_model.zip_code,
                          address_model.country,
                          bidder.attendee.cellphone,
                          bidder.admin_notes,
                          bidder.email_won_bids,
                          ])
