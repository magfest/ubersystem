import random
import re
import string
from collections import OrderedDict
from datetime import datetime

import six
from pytz import UTC
from dateutil import parser as dateparser
from sqlalchemy import exists, func, select, CheckConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.schema import Index, ForeignKey
from sqlalchemy.types import Integer, Uuid, String, DateTime

from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, utcnow, DefaultColumn as Column, Choice
from uber.utils import localized_now, RegistrationCode


__all__ = ['PromoCodeWord', 'PromoCodeGroup', 'PromoCode']


class PromoCodeWord(MagModel):
    """
    Words used to generate promo codes.

    Attributes:
        word (str): The text of this promo code word.
        normalized_word (str): A normalized version of `word`, suitable for
            database queries.
        part_of_speech (int): The part of speech that `word` is.
            Valid values are:

            * 0 `_ADJECTIVE`: `word` is an adjective

            * 1 `_NOUN`: `word` is a noun

            * 2 `_VERB`: `word` is a verb

            * 3 `_ADVERB`: `word` is an adverb

        part_of_speech_str (str): A human readable description of
            `part_of_speech`.
    """

    _ADJECTIVE = 0
    _NOUN = 1
    _VERB = 2
    _ADVERB = 3
    _PART_OF_SPEECH_OPTS = [
        (_ADJECTIVE, 'adjective'),
        (_NOUN, 'noun'),
        (_VERB, 'verb'),
        (_ADVERB, 'adverb')]
    _PARTS_OF_SPEECH = dict(_PART_OF_SPEECH_OPTS)

    word = Column(String)
    part_of_speech = Column(Choice(_PART_OF_SPEECH_OPTS), default=_ADJECTIVE)

    __table_args__ = (
        Index(
            'uq_promo_code_word_normalized_word_part_of_speech',
            func.lower(func.trim(word)),
            part_of_speech,
            unique=True),
        CheckConstraint(func.trim(word) != '', name='ck_promo_code_word_non_empty_word')
    )

    _repr_attr_names = ('word',)

    @hybrid_property
    def normalized_word(self):
        return self.normalize_word(self.word)

    @normalized_word.expression
    def normalized_word(cls):
        return func.lower(func.trim(cls.word))

    @property
    def part_of_speech_str(self):
        return self._PARTS_OF_SPEECH[self.part_of_speech].title()

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
        parts_of_speech = OrderedDict([(i, []) for (i, _) in PromoCodeWord._PART_OF_SPEECH_OPTS])
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


c.PROMO_CODE_WORD_PART_OF_SPEECH_OPTS = PromoCodeWord._PART_OF_SPEECH_OPTS
c.PROMO_CODE_WORD_PARTS_OF_SPEECH = PromoCodeWord._PARTS_OF_SPEECH


class PromoCodeGroup(MagModel):
    name = Column(String)
    code = Column(String, admin_only=True)
    registered = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))
    buyer_id = Column(Uuid(as_uuid=False), ForeignKey('attendee.id', ondelete='SET NULL'), nullable=True)
    buyer = relationship(
        'Attendee', backref='promo_code_groups', lazy='joined',
        foreign_keys=buyer_id,
        cascade='save-update,merge,refresh-expire,expunge')

    email_model_name = 'group'

    @presave_adjustment
    def group_code(self):
        """
        Promo Code Groups can be used one of two ways: Each promo
        code's unique code can be used to claim a specific badge,
        or the groups' code can be used by multiple people to
        claim random badges in the group.

        We don't want this to clash with any promo codes' existing
        codes, so we use that class' generator method.
        """
        if not self.code:
            self.code = RegistrationCode.generate_random_code(PromoCode.code)

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.code)

    @property
    def email(self):
        return self.buyer.email if self.buyer else None

    @hybrid_property
    def total_cost(self):
        return sum(code.cost for code in self.paid_codes if code.cost)

    @total_cost.expression
    def total_cost(cls):
        return select(func.sum(PromoCode.cost)
                      ).where(PromoCode.group_id == cls.id).where(PromoCode.refunded == False  # noqa: E712
                                                                  ).label('total_cost')

    @property
    def paid_codes(self):
        return [code for code in self.promo_codes if not code.refunded]

    @property
    def valid_codes(self):
        return [code for code in self.promo_codes if code.is_valid]

    @property
    def unused_codes(self):
        # Bypasses codes' expiration date; only use this to count
        # how many codes in a group went unused
        return [code for code in self.promo_codes if code.uses_count == 0]

    @property
    def used_promo_codes(self):
        return [code for code in self.promo_codes if code.valid_used_by]

    @property
    def sorted_promo_codes(self):
        return list(sorted(self.promo_codes, key=lambda pc: (not pc.valid_used_by,
                                                             pc.valid_used_by[0].full_name
                                                             if pc.valid_used_by else pc.code)))

    @property
    def hours_since_registered(self):
        if not self.registered:
            return 0
        delta = datetime.now(UTC) - self.registered
        return max(0, delta.total_seconds()) / 60.0 / 60.0

    @property
    def hours_remaining_in_grace_period(self):
        return max(0, c.GROUP_UPDATE_GRACE_PERIOD - self.hours_since_registered)

    @property
    def is_in_grace_period(self):
        return self.hours_remaining_in_grace_period > 0

    @property
    def min_badges_addable(self):
        return 1 if self.hours_remaining_in_grace_period > 0 else c.MIN_GROUP_ADDITION


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

            * 0 `_FIXED_DISCOUNT`: `discount` is interpreted as a fixed
                dollar amount by which the badge price should be reduced. If
                `discount` is 49 and the badge price is normally $100, then
                the discounted badge price would be $51.

            * 1 `_FIXED_PRICE`: `discount` is interpreted as the actual badge
                price. If `discount` is 49, then the discounted badge price
                would be $49.

            * 2 `_PERCENT_DISCOUNT`: `discount` is interpreted as a percentage
                by which the badge price should be reduced. If `discount` is
                20 and the badge price is normally $50, then the discounted
                badge price would $40 ($50 reduced by 20%). If `discount` is
                100, then the price would be 100% off, i.e. a free badge.

        group (relationship): An optional relationship to a PromoCodeGroup
            object, which groups sets of promo codes to make attendee-facing
            "groups"

        cost (int): The cost of this promo code if and when it was bought
          as part of a PromoCodeGroup.

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

    _FIXED_DISCOUNT = 0
    _FIXED_PRICE = 1
    _PERCENT_DISCOUNT = 2
    _DISCOUNT_TYPE_OPTS = [
        (_FIXED_DISCOUNT, 'Fixed Discount'),
        (_FIXED_PRICE, 'Fixed Price'),
        (_PERCENT_DISCOUNT, 'Percent Discount')]

    
    code = Column(String)
    discount = Column(Integer, nullable=True, default=None)
    discount_type = Column(Choice(_DISCOUNT_TYPE_OPTS), default=_FIXED_DISCOUNT)
    expiration_date = Column(DateTime(timezone=True), default=c.ESCHATON)
    uses_allowed = Column(Integer, nullable=True, default=None)
    cost = Column(Integer, nullable=True, default=None)
    admin_notes = Column(String)

    group_id = Column(Uuid(as_uuid=False), ForeignKey('promo_code_group.id', ondelete='SET NULL'), nullable=True)
    group = relationship(
        PromoCodeGroup, backref=backref('promo_codes', lazy='selectin'), lazy='joined',
        foreign_keys=group_id,
        cascade='save-update,merge,refresh-expire,expunge')

    __table_args__ = (
        Index(
            'uq_promo_code_normalized_code',
            func.replace(func.replace(func.lower(code), '-', ''), ' ', ''),
            unique=True),
        CheckConstraint(func.trim(code) != '', name='ck_promo_code_non_empty_code')
    )

    _repr_attr_names = ('code',)

    @classmethod
    def normalize_expiration_date(cls, dt):
        """
        Converts the given datetime to 11:59pm local in the event timezone.
        """
        if isinstance(dt, six.string_types):
            if dt.strip():
                dt = dateparser.parse(dt)
            else:
                dt = c.ESCHATON
        if dt.tzinfo:
            dt = dt.astimezone(c.EVENT_TIMEZONE)
        return c.EVENT_TIMEZONE.localize(dt.replace(hour=23, minute=59, second=59, tzinfo=None))

    @property
    def discount_str(self):
        if self.discount_type == self._FIXED_DISCOUNT and self.discount == 0:
            # This is done to account for Art Show Agent codes, which use the PromoCode class
            return 'No discount'
        elif not self.discount:
            return 'Free badge'

        if self.discount_type == self._FIXED_DISCOUNT:
            return '${} discount'.format(self.discount)
        elif self.discount_type == self._FIXED_PRICE:
            return '${} badge'.format(self.discount)
        else:
            return '%{} discount'.format(self.discount)

    @hybrid_property
    def is_expired(self):
        return self.expiration_date < localized_now()

    @is_expired.expression
    def is_expired(cls):
        return cls.expiration_date < localized_now()

    @hybrid_property
    def group_registered(self):
        if self.group_id:
            return self.group.registered

    @group_registered.expression
    def group_registered(cls):
        return select(PromoCodeGroup.registered).where(PromoCodeGroup.id == cls.group_id).label('group_registered')

    @property
    def is_free(self):
        return not self.discount or (
            self.discount_type == self._PERCENT_DISCOUNT and
            self.discount >= 100
        ) or (
            self.discount_type == self._FIXED_DISCOUNT and
            self.discount >= c.BADGE_PRICE)

    @hybrid_property
    def is_unlimited(self):
        return not self.uses_allowed

    @is_unlimited.expression
    def is_unlimited(cls):
        return cls.uses_allowed == None  # noqa: E711

    @hybrid_property
    def is_valid(self):
        return not self.is_expired and (self.is_unlimited or self.uses_remaining > 0)

    @is_valid.expression
    def is_valid(cls):
        return (cls.expiration_date >= localized_now()) \
            & ((cls.uses_allowed == None) | (cls.uses_remaining > 0))  # noqa: E711

    @hybrid_property
    def normalized_code(self):
        return RegistrationCode.normalize_code(self.code)

    @normalized_code.expression
    def normalized_code(cls):
        return RegistrationCode.sql_normalized_code(cls.code)

    @property
    def valid_used_by(self):
        return list(set([attendee for attendee in self.used_by if attendee.is_valid]))

    @property
    def uses_allowed_str(self):
        uses = self.uses_allowed
        return 'Unlimited uses' if uses is None else '{} use{} allowed'.format(uses, '' if uses == 1 else 's')

    @hybrid_property
    def uses_count(self):
        return len(self.valid_used_by)

    @uses_count.expression
    def uses_count(cls):
        from uber.models.attendee import Attendee
        return select(func.count(Attendee.id)).where(Attendee.promo_code_id == cls.id
                                                       ).where(Attendee.is_valid == True  # noqa: E712
                                                               ).label('uses_count')

    @property
    def uses_count_str(self):
        uses = self.uses_count
        return 'Used by {} attendee{}'.format(uses, '' if uses == 1 else 's')

    @hybrid_property
    def uses_remaining(self):
        return None if self.is_unlimited else self.uses_allowed - self.uses_count

    @uses_remaining.expression
    def uses_remaining(cls):
        return cls.uses_allowed - cls.uses_count

    @property
    def uses_remaining_str(self):
        uses = self.uses_remaining
        return 'Unlimited uses' if uses is None else '{} use{} remaining'.format(uses, '' if uses == 1 else 's')

    @hybrid_property
    def refunded(self):
        return self.used_by and self.used_by[0].badge_status == c.REFUNDED_STATUS

    @refunded.expression
    def refunded(cls):
        from uber.models import Attendee
        return exists().select_from(Attendee).where(cls.id == Attendee.promo_code_id
                                                    ).where(Attendee.badge_status == c.REFUNDED_STATUS)

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
            self.code = RegistrationCode.generate_random_code(PromoCode.code)
        else:
            # Replace multiple whitespace characters with a single space
            self.code = re.sub(r'\s+', ' ', self.code)

        # Always make expiration_date 11:59pm of the given date
        self.expiration_date = self.normalize_expiration_date(self.expiration_date)

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
        if self.discount_type == self._FIXED_DISCOUNT:
            discounted_price = price - self.discount
        elif self.discount_type == self._FIXED_PRICE:
            discounted_price = self.discount
        elif self.discount_type == self._PERCENT_DISCOUNT:
            discounted_price = int(price * ((100.0 - self.discount) / 100.0))

        return min(max(discounted_price, 0), price)


c.PROMO_CODE_DISCOUNT_TYPE_OPTS = PromoCode._DISCOUNT_TYPE_OPTS
