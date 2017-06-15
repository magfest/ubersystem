from uber.common import *


def prereg_money(session):
    preregs = defaultdict(int)
    for attendee in session.query(Attendee):
        preregs['Attendee'] += attendee.amount_paid - attendee.amount_extra
        preregs['extra'] += attendee.amount_extra

    preregs['group_badges'] = sum(g.badge_cost for g in session.query(Group)
                                                               .filter(Group.tables == 0, Group.amount_paid > 0)
                                                               .options(joinedload(Group.attendees)))

    dealers = session.query(Group).filter(Group.tables > 0, Group.amount_paid > 0).options(joinedload(Group.attendees)).all()
    preregs['dealer_tables'] = sum(d.table_cost for d in dealers)
    preregs['dealer_badges'] = sum(d.badge_cost for d in dealers)

    return preregs


def sale_money(session):
    sales = defaultdict(int)
    for sale in session.query(Sale).all():
        sales[sale.what] += sale.cash
    return dict(sales)  # converted to a dict so we can say sales.items in our template


@all_renderable(c.MONEY)
class Root:
    @log_pageview
    def index(self, session):
        sales   = sale_money(session)
        preregs = prereg_money(session)
        total = sum(preregs.values()) + sum(sales.values())
        return {
            'total':   total,
            'preregs': preregs,
            'sales':   sales
        }

    @log_pageview
    def mpoints(self, session):
        groups = defaultdict(list)
        for mpu in session.query(MPointsForCash).options(joinedload(MPointsForCash.attendee).subqueryload(Attendee.group)):
            groups[mpu.attendee and mpu.attendee.group].append(mpu)
        all = [(sum(mpu.amount for mpu in mpus), group, mpus)
               for group, mpus in groups.items()]
        return {'all': sorted(all, reverse=True)}

    @ajax
    def add_promo_code_words(self, session, text='', part_of_speech=0):
        text = text.strip()
        words = []
        if text:
            with Session() as session:
                old_words = set(s for (s,) in session.query(
                    PromoCodeWord.normalized_word).filter(
                        PromoCodeWord.part_of_speech == part_of_speech).all())

            for word in [s for s in shlex.split(text.replace(',', ' ')) if s]:
                if PromoCodeWord.normalize_word(word) not in old_words:
                    words.append(PromoCodeWord().apply(
                        dict(word=word, part_of_speech=part_of_speech)))
            words = [word.word for word in session.bulk_insert(words)]
        return {'words': words}

    @ajax
    def delete_all_promo_code_words(self, session, part_of_speech=None):
        query = session.query(PromoCodeWord)
        if part_of_speech is not None:
            query = query.filter(
                PromoCodeWord.part_of_speech == part_of_speech)
        result = query.delete(synchronize_session=False)
        return {'result': result}

    @ajax
    def delete_promo_code_word(self, session, word=''):
        result = 0
        word = PromoCodeWord.normalize_word(word)
        if word:
            result = session.query(PromoCodeWord).filter(
                PromoCodeWord.normalized_word == word).delete(
                    synchronize_session=False)
        return {'result': result}

    def delete_promo_codes(self, session, id=None, **params):
        query = session.query(PromoCode).filter(PromoCode.uses_count == 0)
        if id is not None:
            ids = [s.strip() for s in id.split(',') if s.strip()]
            query = query.filter(PromoCode.id.in_(ids))
        result = query.delete(synchronize_session=False)

        referer = cherrypy.request.headers.get('Referer', 'view_promo_codes')
        page = urllib.parse.urlparse(referer).path.split('/')[-1]

        raise HTTPRedirect(page + '?message={}',
            '{} promo code{} deleted'.format(
                result, '' if result == 1 else 's'))

    @csv_file
    def export_promo_codes(self, out, session, codes):
        codes = codes or session.query(PromoCode).all()
        out.writerow(['Code', 'Expiration Date', 'Discount', 'Uses'])
        for code in codes:
            out.writerow([
                code.code,
                code.expiration_date,
                code.discount_str,
                code.uses_allowed_str])

    @site_mappable
    @log_pageview
    def generate_promo_codes(
            self,
            session,
            message='',
            is_single_promo_code=0,
            count=1,
            use_words=False,
            **params):

        words = PromoCodeWord.group_by_parts_of_speech(
            session.query(PromoCodeWord).order_by(
                PromoCodeWord.normalized_word).all())

        result = {
            'message': message,
            'promo_codes': [],
            'words': [(i, s) for (i, s) in words.items()]
        }

        try:
            count = int(count)
        except:
            count = 1

        try:
            is_single_promo_code = int(is_single_promo_code)
        except:
            is_single_promo_code = 0

        if cherrypy.request.method == 'POST':
            codes = None
            if is_single_promo_code:
                if params.get('code', '').strip():
                    codes = [params['code']]
                else:
                    count = 1

            if use_words and not codes and \
                    not any(s for (_, s) in words.items()):
                result['message'] = 'Please add some promo code words!'
                return result

            if not codes:
                if use_words:
                    codes = PromoCode.generate_word_code(count)
                else:
                    length = int(params.get('length', 12))
                    segment_length = int(params.get('segment_length', 3))
                    codes = PromoCode.generate_random_code(
                        count, length, segment_length)

            promo_codes = []
            for code in codes:
                params['code'] = code
                promo_codes.append(PromoCode().apply(params))

            message = check_all(promo_codes)
            if message:
                result['message'] = message
                return result

            result['promo_codes'] = session.bulk_insert(promo_codes)
            if len(result['promo_codes']) != count:
                result['message'] = 'Some of the requested promo codes ' \
                    'could not be generated'

        if 'export' in params:
            return self.export_promo_codes(codes=result['promo_codes'])
        return result

    def update_promo_code(self, session, message='', **params):
        if 'id' in params:
            promo_code = session.promo_code(params)

            message = check(promo_code)

            if message:
                session.rollback()
            else:
                if 'expire' in params:
                    promo_code.expiration_date = localized_now() - timedelta(days=1)

                message = 'Promo code updated'
                session.commit()

            raise HTTPRedirect('view_promo_codes?message={}', message)

    @site_mappable
    @log_pageview
    def view_promo_codes(self, session, message='', **params):
        promo_codes = session.query(PromoCode).options(
            joinedload(PromoCode.used_by)).all()
        return {
            'message': message,
            'promo_codes': promo_codes
        }
