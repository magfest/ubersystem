import cherrypy
from barcode import Code39
from barcode.writer import ImageWriter
import re
import math

from decimal import Decimal
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from io import BytesIO

from uber.config import c
from uber.custom_tags import format_currency
from uber.decorators import ajax, all_renderable, credit_card, public
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, ArtShowApplication, ArtShowBidder, ArtShowPayment, ArtShowPiece, ArtShowReceipt, \
                        Attendee, Tracking, ArbitraryCharge, ReceiptItem, ReceiptTransaction, WorkstationAssignment
from uber.utils import check, get_static_file_path, localized_now, Order
from uber.payments import TransactionRequest, ReceiptManager


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'applications': session.query(ArtShowApplication).options(joinedload(ArtShowApplication.attendee))
        }

    def form(self, session, new_app='', message='', **params):
        if new_app and 'attendee_id' in params:
            app = session.art_show_application(params, ignore_csrf=True, bools=['us_only'])
        else:
            if cherrypy.request.method == 'POST' and params.get('id') not in [None, '', 'None']:
                app = session.art_show_application(params.get('id'))
                receipt_items = ReceiptManager.auto_update_receipt(app, session.get_receipt_by_model(app), params)
                session.add_all(receipt_items)
            app = session.art_show_application(params, bools=['us_only'])
        attendee = None
        app_paid = 0 if new_app else app.amount_paid

        attendee_attrs = session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, Attendee.badge_num) \
            .filter(Attendee.first_name != '', Attendee.is_valid == True,  # noqa: E712
                    Attendee.badge_status != c.WATCHED_STATUS)

        attendees = [
            (id, '{} - {}{}'.format(name.title(), c.BADGES[badge_type], ' #{}'.format(badge_num) if badge_num else ''))
            for id, name, badge_type, badge_num in attendee_attrs]

        if cherrypy.request.method == 'POST':
            if new_app:
                attendee, message = \
                    session.attendee_from_art_show_app(**params)
            else:
                attendee = app.attendee
            message = message or check(app)

            if not message:
                if attendee:
                    if params.get('badge_status', ''):
                        attendee.badge_status = params['badge_status']
                    if 'app_paid' in params and int(params['app_paid']) != app_paid and int(params['app_paid']) > 0:
                        session.add(attendee)
                        app.attendee = attendee

                session.add(app)
                if params.get('save_return_to_search', False):
                    return_to = 'index?'
                else:
                    return_to = 'form?id=' + app.id + '&'
                raise HTTPRedirect(
                    return_to + 'message={}', 'Application updated')
        return {
            'message': message,
            'app': app,
            'attendee': attendee,
            'app_paid': app_paid,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'all_attendees': sorted(attendees, key=lambda tup: tup[1]),
            'new_app': new_app,
        }

    def pieces(self, session, id, message=''):
        app = session.art_show_application(id)
        return {
            'app': app,
            'message': message,
        }

    def history(self, session, id):
        app = session.art_show_application(id)
        return {
            'app': app,
            'changes': session.query(Tracking).filter(
                or_(Tracking.links.like('%art_show_application({})%'.format(id)),
                    and_(Tracking.model == 'ArtShowApplication', Tracking.fk_id == id))
                    ).order_by(Tracking.when).all()
        }

    def ops(self, session, message=''):
        return {
            'message': message,
        }

    def close_out(self, session, message='', piece_code='', bidder_num='', **params):
        found_piece, found_bidder, data_error = None, None, ''

        if piece_code:
            if len(piece_code.split('-')) != 2:
                data_error = 'Please enter just one piece code.'
            else:
                artist_id, piece_id = piece_code.split('-')
                try:
                    piece_id = int(piece_id)
                except Exception:
                    data_error = 'Please use the format XXX-# for the piece code.'

            if not data_error:
                piece = session.query(ArtShowPiece).join(ArtShowPiece.app).filter(
                    ArtShowApplication.artist_id == artist_id.upper(),
                    ArtShowPiece.piece_id == piece_id
                )
                if not piece.count():
                    message = 'Could not find piece with code {}.'.format(piece_code)
                elif piece.count() > 1:
                    message = 'Multiple pieces matched the code you entered for some reason.'
                else:
                    found_piece = piece.one()

                if bidder_num:
                    bidder = session.query(ArtShowBidder).filter(ArtShowBidder.bidder_num.ilike(bidder_num))
                    if not bidder.count():
                        message = 'Could not find bidder with number {}.'.format(bidder_num)
                    elif bidder.count() > 1:
                        message = 'Multiple bidders matched the number you entered for some reason.'
                    else:
                        found_bidder = bidder.one().attendee
            else:
                message = data_error

        return {
            'message': message,
            'piece_code': piece_code,
            'bidder_num': bidder_num,
            'piece': found_piece,
            'bidder': found_bidder
        }

    def close_out_piece(self, session, message='', **params):
        if 'id' not in params:
            raise HTTPRedirect('close_out?piece_code={}&bidder_num={}&message={}',
                               params['piece_code'], params['bidder_num'], 'Error: no piece ID submitted.')

        piece = session.art_show_piece(params)
        session.add(piece)

        if piece.status == c.QUICK_SALE and not piece.valid_quick_sale:
            message = 'This piece does not have a valid quick-sale price.'
        elif piece.status == c.RETURN and piece.valid_quick_sale:
            message = 'This piece has a quick-sale price and so cannot yet be marked as Return to Artist.'
        elif (piece.winning_bid or piece.status == c.SOLD) and not piece.valid_for_sale:
            message = 'This piece is not for sale!'
        elif 'bidder_id' not in params:
            if piece.status == c.SOLD:
                message = 'You cannot mark a piece as Sold without a bidder. Please add a bidder number in step 1.'
            elif piece.winning_bid:
                message = 'You cannot enter a winning bid without a bidder. Please add a bidder number in step 1.'
        elif piece.status != c.SOLD:
            if 'bidder_id' in params:
                message = 'You cannot assign a piece to a bidder\'s receipt without marking it as Sold.'
            if piece.winning_bid:
                message = 'You cannot enter a winning bid for a piece without also marking it as Sold.'
        elif piece.status == c.SOLD and not piece.winning_bid:
            message = 'Please enter the winning bid for this piece.'
        elif piece.status == c.SOLD and piece.winning_bid < piece.opening_bid:
            message = 'The winning bid (${}) cannot be less than the minimum bid (${}).'\
                .format(piece.winning_bid, piece.opening_bid)

        if piece.status == c.PAID:
            message = 'Please process sales via the sales page.'

        if 'bidder_id' in params:
            attendee = session.attendee(params['bidder_id'])
            if not attendee:
                message = 'Attendee not found for some reason.'
            elif not attendee.art_show_receipt:
                receipt = ArtShowReceipt(attendee=attendee)
                session.add(receipt)
                session.commit()
            else:
                receipt = attendee.art_show_receipt

            if not message:
                piece.winning_bidder = attendee.art_show_bidder
                piece.receipt = receipt

        if message:
            session.rollback()
            raise HTTPRedirect('close_out?piece_code={}&bidder_num={}&message={}',
                               params['piece_code'], params['bidder_num'], message)
        else:
            raise HTTPRedirect('close_out?message={}',
                               'Close-out successful for piece {}'.format(piece.artist_and_piece_id))

    def artist_check_in_out(self, session, checkout=False, message='', page=1, search_text='', order='first_name'):
        filters = [ArtShowApplication.status == c.APPROVED]
        if checkout:
            filters.append(ArtShowApplication.checked_in != None)  # noqa: E711
        else:
            filters.append(ArtShowApplication.checked_out == None)  # noqa: E711

        search_text = search_text.strip()
        search_filters = []
        if search_text:
            for attr in ['first_name', 'last_name', 'legal_name',
                         'full_name', 'last_first', 'badge_printed_name']:
                search_filters.append(getattr(Attendee, attr).ilike('%' + search_text + '%'))

            for attr in ['artist_name', 'banner_name']:
                search_filters.append(getattr(ArtShowApplication, attr).ilike('%' + search_text + '%'))

        applications = session.query(ArtShowApplication).join(ArtShowApplication.attendee)\
            .filter(*filters).filter(or_(*search_filters))\
            .order_by(Attendee.first_name.desc() if '-' in str(order) else Attendee.first_name)

        count = applications.count()
        page = int(page) or 1

        if not count and search_text:
            message = 'No matches found'

        pages = range(1, int(math.ceil(count / 100)) + 1)
        applications = applications[-100 + 100 * page: 100 * page]

        return {
            'message': message,
            'page': page,
            'pages': pages,
            'search_text': search_text,
            'search_results': bool(search_text),
            'applications': applications,
            'order': Order(order),
            'checkout': checkout,
        }

    @public
    def print_check_in_out_form(self, session, id, checkout='', **params):
        app = session.art_show_application(id)

        return {
            'model': app,
            'type': 'artist',
            'checkout': checkout,
        }

    def print_artist_invoice(self, session, id, **params):
        app = session.art_show_application(id)

        return {
            'app': app,
        }

    @ajax
    def save_and_check_in_out(self, session, **params):
        app = session.art_show_application(params['app_id'])
        attendee = app.attendee
        success = 'Application updated'

        app.apply(params, restricted=False)

        message = check(app)
        if message:
            session.rollback()
            return {'error': message}
        else:
            if 'check_in' in params and params['check_in']:
                app.checked_in = localized_now()
                success = 'Artist successfully checked-in'
            if 'check_out' in params and params['check_out']:
                app.checked_out = localized_now()
                success = 'Artist successfully checked-out'
            session.commit()

        if 'check_in' in params:
            attendee_params = dict(params)
            for field_name in ['country', 'region', 'zip_code', 'address1', 'address2', 'city']:
                attendee_params[field_name] = params.get('attendee_{}'.format(field_name), '')

            attendee.apply(attendee_params, restricted=False)

            if c.COLLECT_FULL_ADDRESS and attendee.country == 'United States':
                attendee.international = False
            elif c.COLLECT_FULL_ADDRESS:
                attendee.international = True

            message = check(attendee)
            if message:
                session.rollback()
                return {'error': message}
            else:
                session.commit()

        piece_ids = params.get('piece_ids' + app.id)

        if piece_ids:
            try:
                session.art_show_piece(piece_ids)
            except Exception:
                pieces = piece_ids
            else:
                pieces = [piece_ids]

            for id in pieces:
                piece = session.art_show_piece(id)
                piece_params = dict()
                for field_name in ['gallery', 'status', 'name', 'opening_bid', 'quick_sale_price']:
                    piece_params[field_name] = params.get('{}{}'.format(field_name, id), '')

                # Correctly handle admins entering '0' for a price
                try:
                    opening_bid = int(piece_params['opening_bid'])
                except Exception:
                    opening_bid = piece_params['opening_bid']
                try:
                    quick_sale_price = int(piece_params['quick_sale_price'])
                except Exception:
                    quick_sale_price = piece_params['quick_sale_price']

                piece_params['for_sale'] = True if opening_bid else False
                piece_params['no_quick_sale'] = False if quick_sale_price else True

                piece.apply(piece_params, restricted=False)
                message = check(piece)
                if message:
                    session.rollback()
                    break
                else:
                    if 'check_in' in params and params['check_in'] and piece.status == c.EXPECTED:
                        piece.status = c.HUNG
                    elif 'check_out' in params and params['check_out'] and piece.status == c.HUNG:
                        piece.status = c.RETURN
                    session.commit()  # We save as we go so it's less annoying if there's an error

        return {
            'id': app.id,
            'error': message,
            'success': success,
        }

    def assign_locations(self, session, message='', **params):
        valid_apps = session.query(ArtShowApplication).filter_by(status=c.APPROVED)

        if cherrypy.request.method == 'POST':
            for app in valid_apps:
                field_name = '{}_locations'.format(app.id)
                if field_name in params:
                    app.locations = params.get(field_name)
                    session.add(app)

            session.commit()

        return {
            'apps': valid_apps,
            'message': message,
        }

    @public
    def bid_sheet_barcode_generator(self, data):
        buffer = BytesIO()
        Code39(data, writer=ImageWriter()).write(buffer)
        buffer.seek(0)
        png_file_output = cherrypy.lib.file_generator(buffer)

        # set response headers last so that exceptions are displayed properly to the client
        cherrypy.response.headers['Content-Type'] = "image/png"

        return png_file_output

    def bid_sheet_pdf(self, session, id, **params):
        import fpdf

        app = session.art_show_application(id)

        if 'piece_id' in params:
            pieces = [session.art_show_piece(params['piece_id'])]
        elif 'piece_ids' in params and params['piece_ids']:
            expanded_ids = re.sub(
                r'(\d+)-(\d+)',
                lambda match: ','.join(
                    str(i) for i in range(
                        int(match.group(1)),
                        int(match.group(2)) + 1
                    )
                ), params['piece_ids']
            )
            id_list = [id.strip() for id in expanded_ids.split(',')]
            pieces = session.query(ArtShowPiece)\
                .filter(ArtShowPiece.piece_id.in_(id_list))\
                .filter(ArtShowPiece.app_id == app.id)\
                .all()
        else:
            pieces = app.art_show_pieces

        pdf = fpdf.FPDF(unit='pt', format='letter')
        pdf.add_font('3of9', '', get_static_file_path('free3of9.ttf'), uni=True)
        pdf.add_font('NotoSans', '', get_static_file_path('NotoSans-Regular.ttf'), uni=True)
        pdf.add_font('NotoSans Bold', '', get_static_file_path('NotoSans-Bold.ttf'), uni=True)
        normal_font_name = 'NotoSans'
        bold_font_name = 'NotoSans Bold'

        def set_fitted_font_size(text, font_size=12, max_size=160):
            pdf.set_font_size(size=font_size)
            while pdf.get_string_width(text) > max_size:
                font_size -= 0.2
                pdf.set_font_size(size=font_size)

        for index, piece in enumerate(sorted(pieces, key=lambda piece: (piece.gallery_label, piece.piece_id))):
            sheet_num = index % 4
            if sheet_num == 0:
                pdf.add_page()

            piece.print_bidsheet(pdf, sheet_num, normal_font_name, bold_font_name, set_fitted_font_size)

        import unicodedata
        filename = str(unicodedata.normalize('NFKD', piece.app.display_name).encode('ascii', 'ignore'))
        filename = re.sub(r'[^\w\s-]', '', filename[1:]).strip().lower()
        filename = re.sub(r'[-\s]+', '-', filename)
        filename = filename + "_" + localized_now().strftime("%m%d%Y_%H%M")

        cherrypy.response.headers['Content-Disposition'] = 'attachment; filename={}.pdf'.format(filename)
        return bytes(pdf.output())

    def bidder_signup(self, session, message='', page=1, search_text='', order=''):
        filters = []
        search_text = search_text.strip()
        if search_text:
            order = order or 'badge_printed_name'
            if re.match(r'\w-[0-9]{4}', search_text):
                attendees = session.query(Attendee).join(Attendee.art_show_bidder).filter(
                    ArtShowBidder.bidder_num.ilike('%{}%'.format(search_text[2:])))
            else:
                # Sorting by bidder number requires a join, which would filter out anyone without a bidder number
                order = 'badge_printed_name' if order == 'bidder_num' else order
                try:
                    badge_num = int(search_text)
                except Exception:
                    filters.append(Attendee.badge_printed_name.ilike('%{}%'.format(search_text)))
                else:
                    filters.append(or_(Attendee.badge_num == badge_num,
                                       Attendee.badge_printed_name.ilike('%{}%'.format(search_text))))
                attendees = session.query(Attendee).filter(*filters).filter(Attendee.is_valid == True)  # noqa: E712
        else:
            attendees = session.query(Attendee).join(Attendee.art_show_bidder)

        if 'bidder_num' in str(order) or not order:
            attendees = attendees.join(Attendee.art_show_bidder).order_by(
                ArtShowBidder.bidder_num.desc() if '-' in str(order) else ArtShowBidder.bidder_num)
        else:
            attendees = attendees.order(order)

        count = attendees.count()
        page = int(page) or 1

        if not count and search_text:
            message = 'No matches found'

        pages = range(1, int(math.ceil(count / 100)) + 1)
        attendees = attendees[-100 + 100*page: 100*page]

        return {
            'message':        message,
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'attendees':      attendees,
            'order':          Order(order),
        }

    @ajax
    def sign_up_bidder(self, session, **params):
        attendee = session.attendee(params['attendee_id'])
        success = 'Bidder saved'
        if params['id']:
            bidder = session.art_show_bidder(params)
        else:
            params.pop('id')
            if 'cellphone' in params and params['cellphone']:
                attendee.cellphone = params.pop('cellphone')
            bidder = ArtShowBidder()
            bidder.apply(params, restricted=False)
            latest_bidder = session.query(ArtShowBidder).filter(ArtShowBidder.id != bidder.id) \
                .order_by(ArtShowBidder.bidder_num_stripped.desc()).first()

            next_num = str(min(latest_bidder.bidder_num_stripped + 1, 9999)).zfill(4) if latest_bidder else "0001"

            bidder.bidder_num = attendee.last_name[:1].upper() + "-" + next_num
            attendee.art_show_bidder = bidder

        if params['complete']:
            bidder.signed_up = localized_now()
            success = 'Bidder signup complete'

        message = check(attendee)
        if not message:
            message = check(bidder)
        if message:
            session.rollback()
            return {'error': message}
        else:
            session.commit()

        return {
            'id': bidder.id,
            'attendee_id': attendee.id,
            'bidder_num': bidder.bidder_num,
            'bidder_id': bidder.id,
            'error': message,
            'success': success
        }

    def print_bidder_form(self, session, id, **params):
        bidder = session.art_show_bidder(id)
        attendee = bidder.attendee

        return {
            'model': attendee,
            'type': 'bidder'
        }

    def sales_search(self, session, message='', page=1, search_text='', order=''):
        filters = []
        search_text = search_text.strip()
        if search_text:
            order = order or 'badge_num'
            if re.match(r'\w-[0-9]{4}', search_text):
                attendees = session.query(Attendee).join(Attendee.art_show_bidder).filter(
                    ArtShowBidder.bidder_num.ilike('%{}%'.format(search_text[2:])))
            else:
                # Sorting by bidder number requires a join, which would filter out anyone without a bidder number
                order = 'badge_num' if order == 'bidder_num' else order
                try:
                    badge_num = int(search_text)
                except Exception:
                    raise HTTPRedirect('sales_search?message={}', 'Please search by bidder number or badge number.')
                else:
                    filters.append(or_(Attendee.badge_num == badge_num))
                attendees = session.query(Attendee).filter(*filters)
        else:
            attendees = session.query(Attendee).join(Attendee.art_show_receipts)

        if 'bidder_num' in str(order):
            attendees = attendees.join(Attendee.art_show_bidder).order_by(
                ArtShowBidder.bidder_num.desc() if '-' in str(order) else ArtShowBidder.bidder_num)
        else:
            attendees = attendees.order(order or 'badge_num')

        count = attendees.count()
        page = int(page) or 1

        if not count and search_text:
            message = 'No matches found'

        if not search_text:
            attendees = [a for a in attendees if a.art_show_receipt and a.art_show_receipt.pieces]

        pages = range(1, int(math.ceil(count / 100)) + 1)
        attendees = attendees[-100 + 100*page: 100*page]

        return {
            'message':        message,
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'attendees':      attendees,
            'order':          Order(order),
        }

    def pieces_bought(self, session, id, search_text='', message='', **params):
        try:
            receipt = session.art_show_receipt(id)
        except Exception:
            attendee = session.attendee(id)
            if not attendee.art_show_receipt:
                receipt = ArtShowReceipt(attendee=attendee)
                session.add(receipt)
                session.commit()
            else:
                receipt = attendee.art_show_receipt
        else:
            attendee = receipt.attendee

        must_choose = False
        unclaimed_pieces = []
        unpaid_pieces = []

        reg_station_id = cherrypy.session.get('reg_station', '')
        workstation_assignment = session.query(WorkstationAssignment)\
            .filter_by(reg_station_id=reg_station_id or -1).first()

        if search_text:
            if re.match(r'\w+-[0-9]+', search_text):
                artist_id, piece_id = search_text.split('-')
                pieces = session.query(ArtShowPiece).join(ArtShowPiece.app).filter(
                    ArtShowPiece.piece_id == int(piece_id),
                    ArtShowApplication.artist_id == artist_id.upper()
                )
            else:
                pieces = session.query(ArtShowPiece).filter(ArtShowPiece.name.ilike('%{}%'.format(search_text)))

            unclaimed_pieces = pieces.filter(ArtShowPiece.buyer == None,  # noqa: E711
                                             ArtShowPiece.status != c.RETURN)
            unclaimed_pieces = [piece for piece in unclaimed_pieces if piece.sale_price > 0]
            unpaid_pieces = pieces.join(ArtShowReceipt).filter(ArtShowReceipt.closed != None,  # noqa: E711
                                                               ArtShowPiece.status != c.PAID)
            unpaid_pieces = [piece for piece in unpaid_pieces if piece.sale_price > 0]

            if pieces.count() == 0:
                message = "No pieces found with ID or title {}.".format(search_text)
            elif len(unclaimed_pieces) == 0 and len(unpaid_pieces) == 0:
                if pieces.count() == 1:
                    msg_piece = pieces.one()
                    if msg_piece.receipt == receipt:
                        message = "That piece ({}) is already on this receipt.".format(msg_piece.artist_and_piece_id)
                    elif msg_piece.sale_price <= 0:
                        message = "That piece ({}) doesn't have a valid sale price." \
                            .format(msg_piece.artist_and_piece_id)
                    elif msg_piece.status == c.RETURN:
                        message = "That piece ({}) is marked {}.".format(msg_piece.artist_and_piece_id,
                                                                         msg_piece.status_label)
                    elif msg_piece in attendee.art_show_purchases:
                        message = "That piece ({}) was already sold to this buyer."\
                            .format(msg_piece.artist_and_piece_id)
                    else:
                        message = "That piece ({}) was already sold to another buyer."\
                            .format(msg_piece.artist_and_piece_id)
                else:
                    message = "None of the matching pieces for '{}' can be claimed.".format(search_text)
            elif len(unclaimed_pieces) > 1 or (len(unclaimed_pieces) == 0 and len(unpaid_pieces) > 1):
                message = "There were multiple pieces found matching '{}.' Please choose one.".format(search_text)
                must_choose = True

            if not message:
                if len(unclaimed_pieces) == 0 and len(unpaid_pieces) == 1:
                    piece = unpaid_pieces[0]
                elif len(unclaimed_pieces) == 1:
                    piece = unclaimed_pieces[0]
                else:
                    message = "Something went wrong! Try again?"

                if not message:
                    piece.receipt = receipt
                    session.add(piece)
                    message = 'Piece {} successfully claimed'.format(piece.artist_and_piece_id)

            if not must_choose:
                raise HTTPRedirect('pieces_bought?id={}&message={}', receipt.id, message)

        return {
            'receipt': receipt,
            'message': message,
            'must_choose': must_choose,
            'pieces': unclaimed_pieces or unpaid_pieces,
            'reg_station_id': reg_station_id,
            'workstation_assignment': workstation_assignment,
        }

    def unclaim_piece(self, session, id, piece_id, **params):
        receipt = session.art_show_receipt(id)
        piece = session.art_show_piece(piece_id)

        if piece.receipt != receipt:
            raise HTTPRedirect('pieces_bought?id={}&message={}',
                               receipt.id,
                               "Can't unclaim piece: it already doesn't belong to this buyer.")
        elif (receipt.owed - piece.sale_price < 0) and receipt.art_show_payments:
            raise HTTPRedirect('pieces_bought?id={}&message={}',
                               receipt.id,
                               "Can't unclaim piece: it's already been paid for.")
        else:
            piece.receipt = None
            session.add(piece)
            raise HTTPRedirect('pieces_bought?id={}&message={}',
                               receipt.id,
                               'Piece {} successfully unclaimed'.format(piece.artist_and_piece_id))

    def record_payment(self, session, id, amount='', type=c.CASH):
        receipt = session.art_show_receipt(id)

        if amount:
            amount = int(Decimal(amount) * 100)

        is_payment = type == str(c.CASH)

        if is_payment:
            amount = amount or receipt.owed
            message = 'Cash payment of {} recorded'.format(format_currency(amount / 100))
        else:
            amount = amount or receipt.paid
            message = 'Refund of {} recorded'.format(format_currency(amount / 100))

        session.add(ArtShowPayment(
            receipt=receipt,
            amount=amount,
            type=type,
        ))

        raise HTTPRedirect('pieces_bought?id={}&message={}', receipt.attendee.id, message)

    def undo_payment(self, session, id, **params):
        payment = session.art_show_payment(id)

        payment_or_refund = "Refund" if payment.amount < 0 else "Payment"

        session.delete(payment)

        raise HTTPRedirect('pieces_bought?id={}&message={}', payment.receipt.attendee.id,
                           payment_or_refund + " deleted")

    def print_receipt(self, session, id, **params):
        receipt = session.art_show_receipt(id)

        if not receipt.closed:
            receipt.closed = localized_now()
            for piece in receipt.pieces:
                piece.status = c.PAID
                session.add(piece)

            session.add(receipt)

            # Now that we're not changing the receipt anymore, record the item total and the cash sum
            attendee_receipt = session.get_receipt_by_model(receipt.attendee, create_if_none="BLANK")
            total_cash = receipt.cash_total
            if total_cash != 0:
                session.add(ReceiptTransaction(
                    receipt_id=attendee_receipt.id,
                    method=c.CASH,
                    desc="{} Art Show Receipt #{}".format(
                        "Payment for" if total_cash > 0 else "Refund for", receipt.invoice_num),
                    amount=total_cash,
                    who=AdminAccount.admin_name() or 'non-admin',
                ))
            session.add(ReceiptItem(
                receipt_id=attendee_receipt.id,
                desc=f"Art Show Receipt #{receipt.invoice_num}",
                amount=receipt.total,
                who=AdminAccount.admin_name() or 'non-admin',
            ))

            session.commit()

        return {
            'receipt': receipt,
        }

    @ajax
    def cancel_payment(self, session, id, stripe_id):
        payment = session.query(ArtShowPayment).filter_by(id=id).first()
        session.delete(payment)
        session.commit()

        return {'message': 'Payment cancelled.'}

    @public
    @ajax
    @credit_card
    def purchases_charge(self, session, id, amount, receipt_id):
        receipt = session.art_show_receipt(receipt_id)
        attendee = session.attendee(id)
        attendee_receipt = session.get_receipt_by_model(attendee, create_if_none="BLANK")
        charge = TransactionRequest(attendee_receipt,
                                    receipt_email=attendee.email,
                                    description='{}ayment for {}\'s art show purchases'.format(
                                                    'P' if int(float(amount)) == receipt.total else 'Partial p',
                                                    attendee.full_name),
                                    amount=int(float(amount)))
        message = charge.prepare_payment()
        if message:
            return {'error': message}
        else:
            payment = ArtShowPayment(
                receipt=receipt,
                amount=charge.intent.amount,
                type=c.STRIPE,
            )
            session.add(payment)
            session.add_all(charge.get_receipt_items_to_add())
            session.commit()
            return {
                'stripe_intent': charge.intent,
                'success_url': 'pieces_bought?id={}&message={}'.format(attendee.id, 'Charge successfully processed'),
                'cancel_url': 'cancel_payment?id={}'.format(payment.id)
            }

    @ajax
    def start_terminal_payment(self, session, model_id='', amount=0, **params):
        from uber.tasks.registration import process_terminal_sale

        error, terminal_id = session.get_assigned_terminal_id()

        if error:
            return {'error': error}

        try:
            receipt = session.art_show_receipt(model_id)
        except NoResultFound:
            try:
                app = session.art_show_application(model_id)
            except NoResultFound:
                return {'error': f"Could not find sale receipt or art show app {model_id}"}
            else:
                description = f"Payment for {app.attendee.full_name}'s Art Show Application"
        else:
            if not amount:
                amount = receipt.owed
            else:
                amount = int(Decimal(amount) * 100)

            description = '{}ayment for Art Show Invoice #{}'.format(
                'P' if int(float(amount)) == receipt.total else 'Partial p',
                receipt.invoice_num)
            model_id = receipt.attendee.id

        c.REDIS_STORE.delete(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id)
        process_terminal_sale.delay(workstation_num=cherrypy.session.get('reg_station'),
                                    terminal_id=terminal_id,
                                    model_id=model_id,
                                    description=description,
                                    use_account_info=False,
                                    amount=amount)
        return {'success': True}

    @ajax
    def record_terminal_payment(self, session, art_receipt_id='', intent_id='', **params):
        if not intent_id:
            return {'error': f"Could not find matching payment to record for ID '{intent_id}'"}

        txn = session.query(ReceiptTransaction).filter_by(intent_id=intent_id).first()

        if not txn:
            return {'error': f"Could not find matching transaction for ID '{intent_id}'"}

        receipt = session.art_show_receipt(art_receipt_id)

        session.add(ArtShowPayment(
            receipt=receipt,
            amount=txn.txn_total,
            type=c.SQUARE
        ))

        session.commit()
        return {'success': True}

    def paid_with_cash(self, session, id):
        if not cherrypy.session.get('reg_station'):
            return {'success': False, 'message': 'You must set a workstation ID to take payments.'}

        app = session.art_show_application(id)
        receipt = session.get_receipt_by_model(app, create_if_none="DEFAULT")
        amount_owed = receipt.current_amount_owed
        if not amount_owed:
            raise HTTPRedirect('form?id={}&message={}', id, "There's no money owed for this application.")

        receipt_manager = ReceiptManager(receipt)
        error = receipt_manager.create_payment_transaction(f"Marked as paid with cash by {AdminAccount.admin_name()}",
                                                           amount=amount_owed, method=c.CASH)
        if error:
            session.rollback()
            raise HTTPRedirect('form?id={}&message={}', id, f"An error occurred: {error}")

        session.add_all(receipt_manager.items_to_add)
        session.commit()
        raise HTTPRedirect('form?id={}&message={}', id,
                           f"Cash payment of {format_currency(amount_owed / 100)} recorded.")

    @public
    def sales_charge_form(self, message='', amount=None, description='',
                          sale_id=None):
        charge = False
        if amount is not None:
            if not description:
                message = "You must enter a brief description " \
                          "of what's being sold"
            else:
                charge = True

        return {
            'message': message,
            'amount': amount,
            'description': description,
            'sale_id': sale_id,
            'charge': charge,
        }

    @public
    @ajax
    @credit_card
    def sales_charge(self, session, id, amount, description):
        charge = TransactionRequest(amount=100 * float(amount), description=description)
        message = charge.create_stripe_intent()
        if message:
            return {'error': message}
        else:
            session.add(ArbitraryCharge(
                amount=int(charge.dollar_amount),
                what=charge.description,
            ))
            return {'stripe_intent': charge.intent,
                    'success_url': 'sales_charge_form?message={}'.format('Charge successfully processed'),
                    'cancel_url': '../merch_admin/cancel_arbitrary_charge'}
