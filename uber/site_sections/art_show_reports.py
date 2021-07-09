from uber.config import c
from uber.decorators import all_renderable, csv_file
from uber.utils import localized_now

from sqlalchemy import func

from uber.models import ArtShowApplication, ArtShowBidder, ArtShowPayment, ArtShowPiece, ArtShowReceipt, Attendee
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
        except:
            message = "Starting invoice number must be an integer."
        if end:
            try:
                end = int(end)
            except:
                message = "Ending invoice number must be an integer or blank."

        if not message:
            filters = [ArtShowReceipt.invoice_num >= start, ArtShowReceipt.closed != None]
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
            'won_pieces': session.query(ArtShowPiece).join(ArtShowPiece.buyer).join(Attendee.art_show_bidder)
                .filter(ArtShowPiece.winning_bid.isnot(None), ArtShowPiece.status == c.SOLD),
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
        general_pieces = session.query(ArtShowPiece).filter(ArtShowPiece.gallery == c.GENERAL)
        mature_pieces = session.query(ArtShowPiece).filter(ArtShowPiece.gallery == c.MATURE)

        general_auctioned = general_pieces.filter(ArtShowPiece.voice_auctioned == True)
        mature_auctioned = mature_pieces.filter(ArtShowPiece.voice_auctioned == True)

        general_sold = general_pieces.filter(ArtShowPiece.status.in_([c.SOLD, c.PAID]))
        mature_sold = mature_pieces.filter(ArtShowPiece.status.in_([c.SOLD, c.PAID]))

        artists_with_pieces = session.query(ArtShowApplication).filter(ArtShowApplication.art_show_pieces != None)

        all_apps = session.query(ArtShowApplication).all()

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
            'general_panels_count': sum([app.panels for app in all_apps]),
            'mature_panels_count': sum([app.panels_ad for app in all_apps]),
            'general_tables_count': sum([app.tables for app in all_apps]),
            'mature_tables_count': sum([app.tables_ad for app in all_apps]),
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

    @csv_file
    def banner_csv(self, out, session):
        out.writerow(['Banner Name', 'Locations'])
        for app in session.query(ArtShowApplication).filter(ArtShowApplication.status != c.DECLINED):
            out.writerow([app.display_name, app.locations])

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
            if app.status == c.PAID:
                paid = "Yes"
            elif app.status == c.APPROVED:
                paid = "No"
            else:
                paid = "N/A"

            if app.delivery_method == c.BY_MAIL:
                address_model = app
            else:
                address_model = app.attendee

            out.writerow([app.status_label,
                          paid,
                          app.artist_name,
                          app.attendee.full_name,
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
                          app.attendee.badge_status_label,
                          app.attendee.badge_printed_name,
                          app.attendee.email,
                          app.attendee.cellphone,
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
                      "QuickSale Price",
                      "Sale Price",
                      ])

        for piece in session.query(ArtShowPiece):
            if piece.type == c.PRINT:
                piece_type = "{} ({} of {})".format(piece.type_label, piece.print_run_num, piece.print_run_total)
            else:
                piece_type = piece.type_label

            out.writerow([piece.app.display_name,
                          piece.app.artist_id,
                          piece.piece_id,
                          piece.name,
                          piece.status_label,
                          piece_type,
                          piece.media,
                          '$' + str(piece.opening_bid) if piece.valid_for_sale else 'N/A',
                          '$' + str(piece.quick_sale_price) if piece.valid_quick_sale else 'N/A',
                          '$' + str(piece.sale_price) if piece.status in [c.SOLD, c.PAID] else 'N/A',
                          ])

    @csv_file
    def bidder_csv(self, out, session):
        out.writerow(["Bidder Number",
                      "Full Name",
                      "Badge Name",
                      "Address 1",
                      "Address 2",
                      "City",
                      "Region",
                      "Postal Code",
                      "Country",
                      "Phone",
                      "Hotel",
                      "Room Number",
                      "Admin Notes",
                      ])

        for bidder in session.query(ArtShowBidder).join(ArtShowBidder.attendee):
            if bidder.attendee.badge_status == c.NOT_ATTENDING and bidder.attendee.art_show_applications:
                address_model = bidder.attendee.art_show_applications[0]
            else:
                address_model = bidder.attendee

            out.writerow([bidder.bidder_num,
                          bidder.attendee.full_name,
                          bidder.attendee.badge_printed_name,
                          address_model.address1,
                          address_model.address2,
                          address_model.city,
                          address_model.region,
                          address_model.zip_code,
                          address_model.country,
                          bidder.attendee.cellphone,
                          bidder.hotel_name,
                          bidder.hotel_room_num,
                          bidder.admin_notes,
                          ])
