import shlex
import urllib
from datetime import timedelta

import cherrypy
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, log_pageview, site_mappable
from uber.errors import HTTPRedirect
from uber.models import PromoCode, PromoCodeWord, Session
from uber.utils import check, check_all, localized_now


@all_renderable()
class Root:
    @site_mappable
    @log_pageview
    def index(self, session, message='', show='admin'):
        which = {
            'all': [],
            'admin': [PromoCode.group_id == None],
            'group': [PromoCode.group_id != None],
            'overused': [PromoCode.uses_remaining < 0]
        }[show]

        promo_codes = session.query(PromoCode).filter(*which).options(joinedload(PromoCode.used_by)).all()
        return {
            'show': show,
            'message': message,
            'promo_codes': promo_codes
        }

    @ajax
    def add_promo_code_words(self, session, text='', part_of_speech=0):
        text = text.strip()
        words = []
        if text:
            with Session() as session:
                old_words = set(s for (s,) in session.query(PromoCodeWord.normalized_word).filter(
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
            query = query.filter(PromoCodeWord.part_of_speech == part_of_speech)
        result = query.delete(synchronize_session=False)
        return {'result': result}

    @ajax
    def delete_promo_code_word(self, session, word=''):
        result = 0
        word = PromoCodeWord.normalize_word(word)
        if word:
            result = session.query(PromoCodeWord).filter(
                PromoCodeWord.normalized_word == word).delete(synchronize_session=False)

        return {'result': result}

    def delete_promo_codes(self, session, id=None, **params):
        query = session.query(PromoCode).filter(PromoCode.uses_count == 0)
        if id is not None:
            ids = [s.strip() for s in id.split(',') if s.strip()]
            query = query.filter(PromoCode.id.in_(ids))
        result = query.delete(synchronize_session=False)

        referer = cherrypy.request.headers.get('Referer', 'index')
        page = urllib.parse.urlparse(referer).path.split('/')[-1]

        raise HTTPRedirect(page + '?message={}', '{} promo code{} deleted'.format(result, '' if result == 1 else 's'))

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
    def generate_promo_codes(self, session, message='', **params):
        defaults = dict(
            is_single_promo_code=1,
            count=1,
            use_words=False,
            length=9,
            segment_length=3,
            code='',
            expiration_date=c.ESCHATON,
            discount_type=0,
            discount=10,
            uses_allowed=1,
            export=False)
        params = dict(defaults, **{k: v for k, v in params.items() if k in defaults})

        params['code'] = params['code'].strip()
        params['expiration_date'] = PromoCode.normalize_expiration_date(params['expiration_date'])

        try:
            params['count'] = int(params['count'])
        except Exception:
            params['count'] = 1

        try:
            params['is_single_promo_code'] = int(params['is_single_promo_code'])
        except Exception:
            params['is_single_promo_code'] = 0

        words = PromoCodeWord.group_by_parts_of_speech(
            session.query(PromoCodeWord).order_by(PromoCodeWord.normalized_word).all())

        result = dict(
            params,
            message=message,
            promo_codes=[],
            words=[(i, s) for (i, s) in words.items()])

        if cherrypy.request.method == 'POST':
            codes = None
            if params['is_single_promo_code']:
                params['count'] = 1
                if params['code']:
                    codes = [params['code']]

            if params['use_words'] and not codes and \
                    not any(s for (_, s) in words.items()):
                result['message'] = 'Please add some promo code words!'
                return result

            if not codes:
                if params['use_words']:
                    codes = PromoCode.generate_word_code(params['count'])
                else:
                    try:
                        length = int(params['length'])
                    except Exception:
                        length = 9
                    try:
                        segment_length = int(params['segment_length'])
                    except Exception:
                        segment_length = 3
                    codes = PromoCode.generate_random_code(
                        params['count'], length, segment_length)

            promo_codes = []
            for code in codes:
                params['code'] = code
                promo_codes.append(PromoCode().apply(params, restricted=False))

            message = check_all(promo_codes)
            if message:
                result['message'] = message
                return result

            result['promo_codes'] = session.bulk_insert(promo_codes)
            generated_count = len(result['promo_codes'])
            if generated_count <= 0:
                result['message'] = "Could not generate any of the requested " \
                    "promo codes. Perhaps they've all been taken already?"
                return result

            if generated_count != params['count']:
                result['message'] = 'Some of the requested promo codes could not be generated'

        if params['export']:
            return self.export_promo_codes(codes=result['promo_codes'])

        result.update(defaults)
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

            raise HTTPRedirect('index?message={}', message)
