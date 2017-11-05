import random
import re
import string
import textwrap
from collections import OrderedDict

from sideboard.lib.sa import CoerceUTF8 as UnicodeText, UTCDateTime
from sqlalchemy import func, select, CheckConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.schema import Index
from sqlalchemy.types import Integer

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import DefaultColumn as Column, Choice
from uber.utils import localized_now


__all__ = ['PromoCodeWord', 'PromoCode']


class PromoCodeWord(MagModel):
    """
    Words used to generate promo codes.

    Attributes:
        word (str): The text of this promo code word.
        normalized_word (str): A normalized version of `word`, suitable for
            database queries.
        part_of_speech (int): The part of speech that `word` is.
            Valid values are:

            * 0 `ADJECTIVE`: `word` is an adjective

            * 1 `NOUN`: `word` is a noun

            * 2 `VERB`: `word` is a verb

            * 3 `ADVERB`: `word` is an adverb

        part_of_speech_str (str): A human readable description of
            `part_of_speech`.
    """

    ADJECTIVE = 0
    NOUN = 1
    VERB = 2
    ADVERB = 3
    PART_OF_SPEECH_OPTS = [
        (ADJECTIVE, 'adjective'),
        (NOUN, 'noun'),
        (VERB, 'verb'),
        (ADVERB, 'adverb')]
    PARTS_OF_SPEECH = dict(PART_OF_SPEECH_OPTS)

    word = Column(UnicodeText)
    part_of_speech = Column(Choice(PART_OF_SPEECH_OPTS), default=ADJECTIVE)

    __table_args__ = (
        Index(
            'uq_promo_code_word_normalized_word_part_of_speech',
            func.lower(func.trim(word)), part_of_speech, unique=True),
        CheckConstraint(
            func.trim(word) != '', name='ck_promo_code_word_non_empty_word'))

    _repr_attr_names = ('word',)

    @hybrid_property
    def normalized_word(self):
        return self.normalize_word(self.word)

    @normalized_word.expression
    def normalized_word(cls):
        return func.lower(func.trim(cls.word))

    @property
    def part_of_speech_str(self):
        return self.PARTS_OF_SPEECH[self.part_of_speech].title()

    @presave_adjustment
    def _attribute_adjustments(self):
        # Replace multiple whitespace characters with a single space
        self.word = re.sub(r'\s+', ' ', self.word.strip())

    @classmethod
    def group_by_parts_of_speech(cls, words):
        """
        Groups a list of words by their part_of_speech.

        Arguments:
            words (list): List of `PromoCodeWord`.

        Returns:
            OrderedDict: A dictionary of words mapped to their part of speech,
                like this::

                    OrderedDict([
                        (0, ['adjective1', 'adjective2']),
                        (1, ['noun1', 'noun2']),
                        (2, ['verb1', 'verb2']),
                        (3, ['adverb1', 'adverb2'])
                    ])
        """
        parts_of_speech = OrderedDict(
            [(i, []) for (i, _) in PromoCodeWord.PART_OF_SPEECH_OPTS])
        for word in words:
            parts_of_speech[word.part_of_speech].append(word.word)
        return parts_of_speech

    @classmethod
    def normalize_word(cls, word):
        """
        Normalizes a word.

        Arguments:
            word (str): A word as typed by an admin.

        Returns:
            str: A copy of `word` converted to all lowercase, and multiple
                whitespace characters replaced by a single space.
        """
        return re.sub(r'\s+', ' ', word.strip().lower())


c.PROMO_CODE_WORD_PART_OF_SPEECH_OPTS = PromoCodeWord.PART_OF_SPEECH_OPTS
c.PROMO_CODE_WORD_PARTS_OF_SPEECH = PromoCodeWord.PARTS_OF_SPEECH


class PromoCode(MagModel):
    """
    Promo codes used by attendees to purchase badges at discounted prices.

    Attributes:
        code (str): The actual textual representation of the promo code. This
            is what the attendee would have to type in during registration to
            receive a discount. `code` may not be an empty string or a string
            consisting entirely of whitespace.
        discount (int): The discount amount that should be applied to the
            purchase price of a badge. The interpretation of this value
            depends on the value of `discount_type`. In any case, a value of
            0 equates to a full discount, i.e. a free badge.
        discount_str (str): A human readable description of the discount.
        discount_type (int): The type of discount this promo code will apply.
            Valid values are:

            * 0 `FIXED_DISCOUNT`: `discount` is interpreted as a fixed
                dollar amount by which the badge price should be reduced. If
                `discount` is 49 and the badge price is normally $100, then
                the discounted badge price would be $51.

            * 1 `FIXED_PRICE`: `discount` is interpreted as the actual badge
                price. If `discount` is 49, then the discounted badge price
                would be $49.

            * 2 `PERCENT_DISCOUNT`: `discount` is interpreted as a percentage
                by which the badge price should be reduced. If `discount` is
                20 and the badge price is normally $50, then the discounted
                badge price would $40 ($50 reduced by 20%). If `discount` is
                100, then the price would be 100% off, i.e. a free badge.

        expiration_date (datetime): The date & time upon which this promo code
            expires. An expired promo code may no longer be used to receive
            discounted badges.
        is_free (bool): True if this promo code will always cause a badge to
            be free. False if this promo code may not cause a badge to be free.

            Note:
                It's possible for this value to be False for a promo code that
                still reduces a badge's price to zero. If there are some other
                discounts that also reduce a badge price (like an age discount)
                then the price may be pushed down to zero.

        is_expired (bool): True if this promo code is expired, False otherwise.
        is_unlimited (bool): True if this promo code may be used an unlimited
            number of times, False otherwise.
        is_valid (bool): True if this promo code is still valid and may be
            used again, False otherwise.
        normalized_code (str): A normalized version of `code` suitable for
            database queries. Normalization converts `code` to all lowercase
            and removes dashes ("-").
        used_by (list): List of attendees that have used this promo code.

            Note:
                This property is declared as a backref in the Attendee class.

        uses_allowed (int): The total number of times this promo code may be
            used. A value of None means this promo code may be used an
            unlimited number of times.
        uses_allowed_str (str): A human readable description of
            uses_allowed.
        uses_count (int): The number of times this promo code has already
            been used.
        uses_count_str (str): A human readable description of uses_count.
        uses_remaining (int): Remaining number of times this promo code may
            be used.
        uses_remaining_str (str): A human readable description of
            uses_remaining.
    """

    FIXED_DISCOUNT = 0
    FIXED_PRICE = 1
    PERCENT_DISCOUNT = 2
    DISCOUNT_TYPE_OPTS = [
        (FIXED_DISCOUNT, 'Fixed Discount'),
        (FIXED_PRICE, 'Fixed Price'),
        (PERCENT_DISCOUNT, 'Percent Discount')]

    AMBIGUOUS_CHARS = {
        '0': 'OQD',
        '1': 'IL',
        '2': 'Z',
        '5': 'S',
        '6': 'G',
        '8': 'B'}

    UNAMBIGUOUS_CHARS = string.digits + string.ascii_uppercase
    for _, s in AMBIGUOUS_CHARS.items():
        UNAMBIGUOUS_CHARS = re.sub('[{}]'.format(s), '', UNAMBIGUOUS_CHARS)

    code = Column(UnicodeText)
    discount = Column(Integer, nullable=True, default=None)
    discount_type = Column(Choice(DISCOUNT_TYPE_OPTS), default=FIXED_DISCOUNT)
    expiration_date = Column(UTCDateTime, default=c.ESCHATON)
    uses_allowed = Column(Integer, nullable=True, default=None)

    __table_args__ = (
        Index(
            'uq_promo_code_normalized_code',
            func.replace(func.replace(func.lower(code), '-', ''), ' ', ''),
            unique=True),
        CheckConstraint(
            func.trim(code) != '', name='ck_promo_code_non_empty_code'))

    _repr_attr_names = ('code',)

    @property
    def discount_str(self):
        if not self.discount:
            return 'Free badge'

        if self.discount_type == self.FIXED_DISCOUNT:
            return '${} discount'.format(self.discount)
        elif self.discount_type == self.FIXED_PRICE:
            return '${} badge'.format(self.discount)
        else:
            return '%{} discount'.format(self.discount)

    @hybrid_property
    def is_expired(self):
        return self.expiration_date < localized_now()

    @is_expired.expression
    def is_expired(cls):
        return cls.expiration_date < localized_now()

    @property
    def is_free(self):
        return not self.discount or (
                self.discount_type == self.PERCENT_DISCOUNT and
                self.discount >= 100
            ) or (
                self.discount_type == self.FIXED_DISCOUNT and
                self.discount >= c.BADGE_PRICE)

    @hybrid_property
    def is_unlimited(self):
        return not self.uses_allowed

    @is_unlimited.expression
    def is_unlimited(cls):
        return cls.uses_allowed == None  # noqa: E711

    @hybrid_property
    def is_valid(self):
        return not self.is_expired and (
            self.is_unlimited or self.uses_remaining > 0)

    @is_valid.expression
    def is_valid(cls):
        return (cls.expiration_date >= localized_now()) & (
            (cls.uses_allowed == None) |  # noqa: E711
            (cls.uses_remaining > 0))

    @hybrid_property
    def normalized_code(self):
        return self.normalize_code(self.code)

    @normalized_code.expression
    def normalized_code(cls):
        return func.replace(
            func.replace(func.lower(cls.code), '-', ''), ' ', '')

    @property
    def uses_allowed_str(self):
        uses = self.uses_allowed
        return 'Unlimited uses' if uses is None \
            else '{} use{} allowed'.format(uses, '' if uses == 1 else 's')

    @hybrid_property
    def uses_count(self):
        return len(self.used_by)

    @uses_count.expression
    def uses_count(cls):
        from uber.models.attendee import Attendee
        return select([func.count(Attendee.id)]).where(
            Attendee.promo_code_id == cls.id).label('uses_count')

    @property
    def uses_count_str(self):
        uses = self.uses_count
        return 'Used by {} attendee{}'.format(uses, '' if uses == 1 else 's')

    @hybrid_property
    def uses_remaining(self):
        return None if self.is_unlimited else \
            self.uses_allowed - self.uses_count

    @uses_remaining.expression
    def uses_remaining(cls):
        return cls.uses_allowed - cls.uses_count

    @property
    def uses_remaining_str(self):
        uses = self.uses_remaining
        return 'Unlimited uses' if uses is None \
            else '{} use{} remaining'.format(uses, '' if uses == 1 else 's')

    @presave_adjustment
    def _attribute_adjustments(self):
        # If 'uses_allowed' is empty, then this is an unlimited use code
        if not self.uses_allowed:
            self.uses_allowed = None

        # If 'discount' is empty, then this is a full discount, free badge
        if not self.discount:
            self.discount = None

        self.code = self.code.strip() if self.code else ''
        if not self.code:
            # If 'code' is empty, then generate a random code
            self.code = self.generate_random_code()
        else:
            # Replace multiple whitespace characters with a single space
            self.code = re.sub(r'\s+', ' ', self.code)

    def calculate_discounted_price(self, price):
        """
        Returns the discounted price based on the promo code's `discount_type`.

        Args:
            price (int): The badge price in whole dollars.

        Returns:
            int: The discounted price. The returned number will never be
                less than zero or greater than `price`. If `price` is None
                or a negative number, then the return value will always be 0.
        """
        if not self.discount or not price or price < 0:
            return 0

        discounted_price = price
        if self.discount_type == self.FIXED_DISCOUNT:
            discounted_price = price - self.discount
        elif self.discount_type == self.FIXED_PRICE:
            discounted_price = self.discount
        elif self.discount_type == self.PERCENT_DISCOUNT:
            discounted_price = int(price * ((100.0 - self.discount) / 100.0))

        return min(max(discounted_price, 0), price)

    @classmethod
    def _generate_code(cls, generator, count=None):
        """
        Helper method to limit collisions for the other generate() methods.

        Arguments:
            generator (callable): Function that returns a newly generated code.
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """
        from uber.models import Session
        with Session() as session:
            # Kind of inefficient, but doing one big query for all the existing
            # codes will be faster than a separate query for each new code.
            old_codes = set(s for (s,) in session.query(cls.code).all())

        # Set an upper limit on the number of collisions we'll allow,
        # otherwise this loop could potentially run forever.
        max_collisions = 100
        collisions = 0
        codes = set()
        while len(codes) < (1 if count is None else count):
            code = generator().strip()
            if not code:
                break
            if code in codes or code in old_codes:
                collisions += 1
                if collisions >= max_collisions:
                    break
            else:
                codes.add(code)
        return (codes.pop() if codes else None) if count is None else codes

    @classmethod
    def generate_random_code(cls, count=None, length=9, segment_length=3):
        """
        Generates a random promo code.

        With `length` = 12 and `segment_length` = 3::

            XXX-XXX-XXX-XXX

        With `length` = 6 and `segment_length` = 2::

            XX-XX-XX

        Arguments:
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.
            length (int): The number of characters to use for the code.
            segment_length (int): The length of each segment within the code.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """

        # The actual generator function, called repeatedly by `_generate_code`
        def _generate_random_code():
            letters = ''.join(
                random.choice(cls.UNAMBIGUOUS_CHARS) for _ in range(length))
            return '-'.join(textwrap.wrap(letters, segment_length))

        return cls._generate_code(_generate_random_code, count=count)

    @classmethod
    def generate_word_code(cls, count=None):
        """
        Generates a promo code consisting of words from `PromoCodeWord`.

        Arguments:
            count (int): The number of codes to generate. If `count` is `None`,
                then a single code will be generated. Defaults to `None`.

        Returns:
            If an `int` value was passed for `count`, then a `list` of newly
            generated codes is returned. If `count` is `None`, then a single
            `str` is returned.
        """
        from uber.models import Session
        with Session() as session:
            words = PromoCodeWord.group_by_parts_of_speech(
                session.query(PromoCodeWord).order_by(
                    PromoCodeWord.normalized_word).all())

        # The actual generator function, called repeatedly by `_generate_code`
        def _generate_word_code():
            code_words = []
            for part_of_speech, _ in PromoCodeWord.PART_OF_SPEECH_OPTS:
                if words[part_of_speech]:
                    code_words.append(random.choice(words[part_of_speech]))
            return ' '.join(code_words)

        return cls._generate_code(_generate_word_code, count=count)

    @classmethod
    def disambiguate_code(cls, code):
        """
        Removes ambiguous characters in a promo code supplied by an attendee.

        Arguments:
            code (str): A promo code as typed by an attendee.

        Returns:
            str: A copy of `code` with all ambiguous characters replaced by
                their unambiguous equivalent.
        """
        code = cls.normalize_code(code)
        if not code:
            return ''
        for unambiguous, ambiguous in cls.AMBIGUOUS_CHARS.items():
            ambiguous_pattern = '[{}]'.format(ambiguous.lower())
            code = re.sub(ambiguous_pattern, unambiguous.lower(), code)
        return code

    @classmethod
    def normalize_code(cls, code):
        """
        Normalizes a promo code supplied by an attendee.

        Arguments:
            code (str): A promo code as typed by an attendee.

        Returns:
            str: A copy of `code` converted to all lowercase, with dashes ("-")
                and whitespace characters removed.
        """
        if not code:
            return ''
        return re.sub(r'[\s\-]+', '', code.lower())


c.PROMO_CODE_DISCOUNT_TYPE_OPTS = PromoCode.DISCOUNT_TYPE_OPTS
