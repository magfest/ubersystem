import cherrypy
from barcode import Code39
from barcode.writer import ImageWriter
import re
import math
import six

from datetime import datetime
from decimal import Decimal
from pockets.autolog import log
from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from io import BytesIO

from uber.config import c
from uber.custom_tags import format_currency, readable_join
from uber.decorators import ajax, all_renderable, credit_card, public
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, ArtShowApplication, ArtShowBidder, ArtShowPayment, ArtShowPiece, ArtShowReceipt, \
                        Attendee, BadgeInfo, Email, Tracking, PageViewTracking, ReceiptItem, ReceiptTransaction, WorkstationAssignment
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
                receipt_items = ReceiptManager.auto_update_receipt(app, session.get_receipt_by_model(app), params.copy())
                session.add_all(receipt_items)
            app = session.art_show_application(params, bools=['us_only'])
        attendee = None
        app_paid = 0 if new_app else app.amount_paid

        attendee_attrs = session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, BadgeInfo.ident) \
            .outerjoin(Attendee.active_badge).filter(Attendee.first_name != '', Attendee.is_valid == True,  # noqa: E712
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
            'emails': session.query(Email).filter(Email.fk_id == id).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(
                or_(Tracking.links.like('%art_show_application({})%'.format(id)),
                    and_(Tracking.model == 'ArtShowApplication', Tracking.fk_id == id))
                    ).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(app)),
        }

    def ops(self, session, message=''):
        return {
            'message': message,
        }

    def close_out(self, session, message='', piece_code='', bidder_num='', winning_bid='', **params):
        found_piece, found_bidder = None, None

        if piece_code:
            if len(piece_code.split('-')) != 2:
                message = 'Please enter just one piece code.'
            else:
                artist_id, piece_id = piece_code.split('-')
                try:
                    piece_id = int(piece_id)
                except Exception:
                    message = 'Please use the format XXX-# for the piece code.'

            if not message:
                piece = session.query(ArtShowPiece).join(ArtShowPiece.app).filter(
                    or_(ArtShowApplication.artist_id == artist_id.upper(),
                        ArtShowApplication.artist_id_ad == artist_id.upper()),
                    ArtShowPiece.piece_id == piece_id
                )
                if not piece.count():
                    message = 'Could not find piece with code {}.'.format(piece_code)
                elif piece.count() > 1:
                    message = 'Multiple pieces matched the code you entered for some reason.'
                else:
                    found_piece = piece.one()

        if found_piece and cherrypy.request.method == 'POST':
            action = params.get('action', '')
            if action in ['set_winner', 'voice_auction'] and not found_piece.valid_for_sale:
                message = "This piece is not for sale and cannot have any bids."
            elif action != 'get_info' and found_piece.status in [c.PAID, c.RETURN]:
                message = "You cannot close out a piece that has been marked as paid for or returned to artist."
            elif action == 'voice_auction':
                found_piece.status = c.VOICE_AUCTION
                session.add(found_piece)
            elif action == 'no_bids':
                if found_piece.valid_quick_sale:
                    found_piece.status = c.QUICK_SALE
                    message = f"Piece {found_piece.artist_and_piece_id} set to {found_piece.status_label} for {format_currency(found_piece.quick_sale_price)}."
                else:
                    found_piece.status = c.RETURN
                session.add(found_piece)
                session.commit()
            elif action == 'get_info':
                message = f"Piece {found_piece.artist_and_piece_id} information retrieved."
                found_piece.history = session.query(Tracking).filter_by(fk_id=found_piece.id)
            elif action == 'set_winner':
                if not bidder_num:
                    message = "Please enter the winning bidder number."
                elif not winning_bid:
                    message = "Please enter a winning bid."
                elif not winning_bid.isdigit():
                    message = "Please enter only numbers for the winning bid."
                elif int(winning_bid) < found_piece.opening_bid:
                    message = f'The winning bid ({format_currency(winning_bid)}) cannot be less than the minimum bid ({format_currency(found_piece.opening_bid)}).'
                else:
                    bidder = session.query(ArtShowBidder).filter(ArtShowBidder.bidder_num.ilike(bidder_num))
                    if not bidder.count():
                        message = 'Could not find bidder with number {}.'.format(bidder_num)
                    elif bidder.count() > 1:
                        message = 'Multiple bidders matched the number you entered for some reason.'
                    else:
                        found_bidder = bidder.one()
                        if not found_bidder.attendee:
                            message = "This bidder number does not have an attendee attached so we cannot sell anything to them."

                if found_bidder and not message:
                    if not found_bidder.attendee.art_show_receipt:
                        receipt = ArtShowReceipt(attendee=found_bidder.attendee)
                        session.add(receipt)
                        session.commit()
                    else:
                        receipt = found_bidder.attendee.art_show_receipt

                    if not message:
                        found_piece.status = c.SOLD
                        found_piece.winning_bid = int(winning_bid)
                        found_piece.winning_bidder = found_bidder
                        found_piece.receipt = receipt
                        session.add(found_piece)
                        if found_bidder.attendee.badge_printed_name:
                            bidder_name = f"{found_bidder.attendee.badge_printed_name} ({found_bidder.attendee.full_name})"
                        else:
                            bidder_name = f"{found_bidder.attendee.full_name}"
                        message = f"Piece {found_piece.artist_and_piece_id} set to {found_piece.status_label} for {format_currency(winning_bid)} to {bidder_num}, {bidder_name}."
                        session.commit()

            if not message:
                session.commit()
                message = f"Piece {found_piece.artist_and_piece_id} set to {found_piece.status_label}."

        return {
            'message': message,
            'piece_code': piece_code,
            'bidder_num': bidder_num,
            'winning_bid': winning_bid,
            'piece': found_piece if params.get('action', '') == 'get_info' else None,
        }

    def artist_check_in_out(self, session, checkout=False, hanging=False, message='', page=1, search_text='', order='first_name'):
        filters = [ArtShowApplication.status == c.APPROVED]
        if checkout:
            filters.append(ArtShowApplication.checked_in != None)  # noqa: E711
        else:
            filters.append(ArtShowApplication.checked_out == None)  # noqa: E711

        if hanging:
            filters.append(ArtShowApplication.art_show_pieces.any(ArtShowPiece.status == c.HANGING))

        search_text = search_text.strip()
        search_filters = []
        if search_text:
            for attr in ['first_name', 'last_name', 'legal_name',
                         'full_name', 'last_first', 'badge_printed_name']:
                search_filters.append(getattr(Attendee, attr).ilike('%' + search_text + '%'))

            for attr in ['artist_name', 'banner_name', 'artist_id', 'artist_id_ad']:
                search_filters.append(getattr(ArtShowApplication, attr).ilike('%' + search_text + '%'))

        applications = session.query(ArtShowApplication).join(ArtShowApplication.attendee)\
            .filter(*filters).filter(or_(*search_filters))\
            .order_by(Attendee.first_name.desc() if '-' in str(order) else Attendee.first_name).options(
                joinedload(ArtShowApplication.art_show_pieces))

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
            'hanging': hanging,
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
            return {'error': message, 'app_id': app.id}
        else:
            if params.get('check_in', ''):
                app.checked_in = localized_now()
                success = 'Artist successfully checked-in'
            if params.get('check_out', ''):
                app.checked_out = localized_now()
                success = 'Artist successfully checked-out'
            if params.get('hanging', ''):
                success = 'Art marked as Hanging'
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
                return {'error': message, 'app_id': app.id}
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
        if not message:
            for piece in app.art_show_pieces:
                if params.get('hanging', None) and piece.status == c.EXPECTED:
                    piece.status = c.HANGING
                elif params.get('check_in', None) and piece.status in [c.EXPECTED, c.HANGING]:
                    piece.status = c.HUNG
                elif params.get('check_out', None) and piece.status == c.HUNG:
                    if piece.orig_value_of('status') == c.PAID:
                        # Accounts for the surprisingly-common situation where an
                        # artist checks out WHILE their pieces are actively being paid for
                        piece.status = c.PAID
                    else:
                        piece.status = c.RETURN
            session.commit()

        return {
            'id': app.id,
            'error': message,
            'success': success,
        }

    @ajax
    def update_location(self, session, message='', **params):
        app = session.art_show_application(params)
        session.commit()
        return {'success': True,
                'message': f"Updated {app.artist_or_full_name}'s location."}

    @ajax
    def update_all(self, session, message='', **params):
        if 'id' in params:
            app_list = []
            if isinstance(params.get('id'), six.string_types):
                params['id'] = [params.get('id')]

            for id in params.get('id'):
                app_params = {key.replace(f'_{id}', ''): val for key, val in params.items() if f'_{id}' in key}
                app_params['id'] = id
                app = session.art_show_application(app_params)
                if app.locations != app.orig_value_of('locations'):
                    app_list.append(app.artist_or_full_name)

            session.commit()
            message = "No locations to update." if not app_list \
                else f"Updated the following applications: {readable_join(app_list)}"

            return {'success': True,
                    'message': message}

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
            if re.match(r'^[a-zA-Z]-[0-9]+', search_text):
                attendees = session.query(Attendee).join(Attendee.art_show_bidder).filter(
                    ArtShowBidder.bidder_num.ilike(search_text.lower()))
                if not attendees.first():
                    existing_bidder_num = session.query(Attendee).join(Attendee.art_show_bidder).filter(
                        ArtShowBidder.bidder_num.ilike(f"%{ArtShowBidder.strip_bidder_num(search_text)}%"))
                    message = f"There is no one with the bidder number {search_text}."
                    if existing_bidder_num.first():
                        message += f" Showing bidder {existing_bidder_num.first().art_show_bidder.bidder_num} instead."
                        attendees = existing_bidder_num
            else:
                if c.INDEPENDENT_ART_SHOW:
                    # Independent art shows likely won't have badge numbers or badge names
                    # so they can search by anything
                    attendees, error = session.search(search_text, Attendee.is_valid == True)  # noqa: E712
                    if error:
                        raise HTTPRedirect('bidder_signup?search_text={}&order={}&message={}'
                                        ).format(search_text, order, error)
                else:
                    # For systems that run registration, search is limited for data privacy
                    try:
                        badge_num = int(search_text)
                    except Exception:
                        filters.append(Attendee.badge_printed_name.ilike('%{}%'.format(search_text)))
                    else:
                        filters.append(or_(BadgeInfo.ident == badge_num,
                                           and_(Attendee.art_show_bidder != None,
                                                ArtShowBidder.bidder_num.ilike('%{search_text}%'))))
                    attendees = session.query(Attendee).join(BadgeInfo).outerjoin(
                        ArtShowBidder).filter(*filters).filter(Attendee.is_valid == True)  # noqa: E712
        else:
            attendees = session.query(Attendee).join(Attendee.art_show_bidder)

        if 'bidder_num' in str(order) or not order:
            attendees = attendees.outerjoin(Attendee.art_show_bidder).order_by(
                ArtShowBidder.bidder_num.desc() if '-' in str(order) else ArtShowBidder.bidder_num)
        else:
            attendees = attendees.order(order)

        count = attendees.count()
        page = int(page) or 1

        if not count and search_text and not message:
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
        try:
            attendee = session.attendee(params['attendee_id'])
        except NoResultFound:
            if c.INDEPENDENT_ART_SHOW:
                attendee = Attendee(
                    id=params['attendee_id'],
                    placeholder=True,
                    badge_status=c.NOT_ATTENDING,
                    )
                session.add(attendee)
            else:
                return {'error': "No attendee found for this bidder!", 'attendee_id': params['attendee_id']}

        success = 'Bidder saved'
        missing_fields = []

        for field_name in params.copy().keys():
            if params.get(field_name, None):
                if hasattr(attendee, field_name) and (not hasattr(ArtShowBidder(), field_name) or field_name == 'email'):
                    setattr(attendee, field_name, params.pop(field_name))
            elif field_name in ArtShowBidder.required_fields.keys():
                missing_fields.append(ArtShowBidder.required_fields[field_name])

        if missing_fields:
            return {'error': "Please fill out the following fields: " + readable_join(missing_fields) + ".",
                    'attendee_id': attendee.id}

        if 'phone_type' not in params:
            return {'error': "You must select whether your phone number is a mobile number or a landline.",
                    'attendee_id': attendee.id}
        
        if 'pickup_time_acknowledged' not in params:
            return {'error': "You must acknowledge that you understand our art pickup policies.",
                    'attendee_id': attendee.id}

        if not re.match("^[a-zA-Z]-[0-9]+", params['bidder_num']):
            return {'error': "Bidder numbers must be in the format X-000 (e.g., A-100).",
                    'attendee_id': attendee.id}

        if params['id']:
            bidder = session.art_show_bidder(params, bools=['email_won_bids'])
        else:
            params.pop('id')
            bidder = ArtShowBidder()
            attendee.art_show_bidder = bidder

        bidder.apply(params, restricted=False, bools=['email_won_bids'])

        bidder_num_dupe = session.query(ArtShowBidder).filter(
            ArtShowBidder.id != bidder.id,
            ArtShowBidder.bidder_num.ilike(f"%{ArtShowBidder.strip_bidder_num(params.get('bidder_num'))}%")).first()
        if bidder_num_dupe:
            session.rollback()
            return {
                'error': f"The bidder number {bidder_num_dupe.bidder_num[2:]} already belongs to bidder"
                            f" {bidder_num_dupe.bidder_num}.",
                'attendee_id': attendee.id
            }

        if params['complete']:
            bidder.signed_up = localized_now()
            success = 'Bidder signup complete'

        message = check(attendee)
        if not message:
            message = check(bidder)
        if message:
            session.rollback()
            return {'error': message, 'attendee_id': attendee.id}
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
            if re.match(r'^[a-zA-Z]-[0-9]+', search_text):
                attendees = session.query(Attendee).join(Attendee.art_show_bidder).filter(
                    ArtShowBidder.bidder_num.ilike('%{}%'.format(ArtShowBidder.strip_bidder_num(search_text))))
            else:
                # Sorting by bidder number requires a join, which would filter out anyone without a bidder number
                order = 'badge_num' if order == 'bidder_num' else order
                try:
                    badge_num = int(search_text)
                except Exception:
                    raise HTTPRedirect('sales_search?message={}', 'Please search by bidder number or badge number.')
                else:
                    filters.append(or_(BadgeInfo.ident == badge_num))
                attendees = session.query(Attendee).join(BadgeInfo).filter(*filters)
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
            if re.match(r'^[a-zA-Z]-[0-9]+', search_text):
                artist_id, piece_id = search_text.split('-')
                pieces = session.query(ArtShowPiece).join(ArtShowPiece.app).filter(
                    ArtShowPiece.piece_id == int(piece_id),
                    or_(ArtShowApplication.artist_id == artist_id.upper(),
                        ArtShowApplication.artist_id_ad == artist_id.upper())
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

    def print_receipt(self, session, id, close=False, **params):
        receipt = session.art_show_receipt(id)

        if close and True:
            receipt.closed = localized_now()
            for piece in receipt.pieces:
                piece.status = c.PAID
                session.add(piece)

            session.add(receipt)

            # Now that we're not changing the receipt anymore, record the item total and the cash sum
            attendee_receipt = session.get_receipt_by_model(receipt.attendee, create_if_none="BLANK")
            total_cash = receipt.cash_total
            if total_cash != 0:
                cash_txn = ReceiptTransaction(
                    receipt_id=attendee_receipt.id,
                    method=c.CASH,
                    department=c.ART_SHOW_RECEIPT_ITEM,
                    desc="{} Art Show Invoice #{}".format(
                        "Payment for" if total_cash > 0 else "Refund for", receipt.invoice_num),
                    amount=total_cash,
                    who=AdminAccount.admin_name() or 'non-admin',
                )
                session.add(cash_txn)
            session.commit()
            session.refresh(attendee_receipt)

            sales_item = ReceiptItem(
                purchaser_id=receipt.attendee.id,
                receipt_id=attendee_receipt.id,
                fk_id=receipt.id,
                fk_model="ArtShowReceipt",
                department=c.ART_SHOW_RECEIPT_ITEM,
                category=c.PURCHASE,
                desc=f"Art Show Receipt #{receipt.invoice_num}",
                amount=receipt.total,
                who=AdminAccount.admin_name() or 'non-admin',
            )

            main_txn = None
            cash_total, credit_total, credit_num = 0, 0, 0
            for txn in [txn for txn in attendee_receipt.receipt_txns if f"Art Show Invoice #{receipt.invoice_num}" in txn.desc]:
                if not main_txn or txn.amount > main_txn.amount:
                    main_txn = txn
                if txn.method == c.CASH:
                    cash_total += txn.amount
                else:
                    credit_num += 1
                    credit_total += txn.amount

            log.error(main_txn)

            admin_notes = []
            if cash_total:
                admin_notes.append(f"Cash: {format_currency(cash_total / 100)}")
            if credit_total:
                credit_note = f"Credit: {format_currency(credit_total / 100)}"
                if credit_num > 1:
                    credit_note += f" ({credit_num} payments)"
                admin_notes.append(credit_note)
            
            log.error(admin_notes)
            log.error(sales_item)

            sales_item.receipt_txn = main_txn
            sales_item.admin_notes = "; ".join(admin_notes)
            sales_item.closed = datetime.now()
            session.add(sales_item)
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
                                    description='{}ayment for Art Show Invoice #{}'.format(
                                                    'P' if int(float(amount)) == receipt.total else 'Partial p',
                                                    receipt.invoice_num),
                                    amount=int(float(amount)))
        message = charge.prepare_payment(department=c.ART_SHOW_RECEIPT_ITEM)
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
        session.check_receipt_closed(receipt)
        raise HTTPRedirect('form?id={}&message={}', id,
                           f"Cash payment of {format_currency(amount_owed / 100)} recorded.")
