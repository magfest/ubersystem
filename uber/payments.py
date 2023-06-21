import importlib
import math
import os
import random
import re
import string
import traceback
import json
from typing import Iterable
import urllib
from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
from glob import glob
from os.path import basename
from random import randrange
from rpctools.jsonrpc import ServerProxy
from urllib.parse import urlparse, urljoin
from uuid import uuid4

import cherrypy
import phonenumbers
import stripe
from authlib.integrations.requests_client import OAuth2Session
from phonenumbers import PhoneNumberFormat
from pockets import cached_property, classproperty, floor_datetime, is_listy, listify
from pockets.autolog import log
from sideboard.lib import threadlocal
from pytz import UTC

import uber
from uber.config import c, _config, signnow_sdk
from uber.errors import CSRFException, HTTPRedirect
from uber.utils import report_critical_exception

class MockStripeIntent(dict):
    """
    Stripe and Authorize.net use radically different workflows: Stripe has you request a payment intent
    before it collects CC details, and Authorize.net requires CC details (or a token) before it will
    do anything.
    
    We prefer Stripe's method as this creates a record in our system before payment is attempted in
    case anything goes wrong. This class lets us use Stripe's workflow in our page handlers with 
    minimal disruptions.
    """
    def __init__(self, amount, description, receipt_email=''):
        self.id = str(uuid4()).replace('-', '')[:20]
        self.amount = amount
        self.description = description
        self.receipt_email = receipt_email
        self.charges = None

        # And now for the serializable info!
        dict.__init__(self, id=self.id, amount=amount, description=description, receipt_email=receipt_email, charges=self.charges)


class Charge:
    def __init__(self, targets=(), amount=0, description=None, receipt_email=''):
        self._targets = listify(targets)
        self._description = description
        self._receipt_email = receipt_email
        self._current_cost = amount

    @classproperty
    def paid_preregs(cls):
        return cherrypy.session.setdefault('paid_preregs', [])

    @classproperty
    def unpaid_preregs(cls):
        return cherrypy.session.setdefault('unpaid_preregs', OrderedDict())

    @classproperty
    def pending_preregs(cls):
        return cherrypy.session.setdefault('pending_preregs', OrderedDict())
    
    @classproperty
    def stripe_intent_id(cls):
        return cherrypy.session.get('stripe_intent_id', '')
    
    @classproperty
    def universal_promo_codes(cls):
        return cherrypy.session.setdefault('universal_promo_codes', {})

    @classmethod
    def get_unpaid_promo_code_uses_count(cls, id, already_counted_attendee_ids=None):
        attendees_with_promo_code = set()
        if already_counted_attendee_ids:
            attendees_with_promo_code.update(listify(already_counted_attendee_ids))

        promo_code_count = 0

        targets = [t for t in cls.unpaid_preregs.values() if '_model' in t]
        for target in targets:
            if target['_model'] == 'Attendee':
                if target.get('id') not in attendees_with_promo_code \
                        and target.get('promo_code') \
                        and target['promo_code'].get('id') == id:
                    attendees_with_promo_code.add(target.get('id'))
                    promo_code_count += 1

            elif target['_model'] == 'Group':
                for attendee in target.get('attendees', []):
                    if attendee.get('id') not in attendees_with_promo_code \
                            and attendee.get('promo_code') \
                            and attendee['promo_code'].get('id') == id:
                        attendees_with_promo_code.add(attendee.get('id'))
                        promo_code_count += 1

            elif target['_model'] == 'PromoCode' and target.get('id') == id:
                # Should never get here
                promo_code_count += 1

        return promo_code_count

    @classmethod
    def to_sessionized(cls, m, name='', badges=0):
        from uber.models import Attendee, Group
        if is_listy(m):
            return [cls.to_sessionized(t) for t in m]
        elif isinstance(m, dict):
            return m
        elif isinstance(m, Attendee):
            d = m.to_dict(
                Attendee.to_dict_default_attrs
                + ['promo_code']
                + list(Attendee._extra_apply_attrs_restricted))
            d['name'] = name
            d['badges'] = badges
            return d
        elif isinstance(m, Group):
            return m.to_dict(
                Group.to_dict_default_attrs
                + ['attendees']
                + list(Group._extra_apply_attrs_restricted))
        else:
            raise AssertionError('{} is not an attendee or group'.format(m))

    @classmethod
    def from_sessionized(cls, d):
        if is_listy(d):
            return [cls.from_sessionized(t) for t in d]
        elif isinstance(d, dict):
            assert d['_model'] in {'Attendee', 'Group'}
            if d['_model'] == 'Group':
                return cls.from_sessionized_group(d)
            else:
                return cls.from_sessionized_attendee(d)
        else:
            return d

    @classmethod
    def from_sessionized_group(cls, d):
        d = dict(d, attendees=[cls.from_sessionized_attendee(a) for a in d.get('attendees', [])])
        return uber.models.Group(_defer_defaults_=True, **d)

    @classmethod
    def from_sessionized_attendee(cls, d):
        if d.get('promo_code'):
            d = dict(d, promo_code=uber.models.PromoCode(_defer_defaults_=True, **d['promo_code']))

        # These aren't valid properties on the model, so they're removed and re-added
        name = d.pop('name', '')
        badges = d.pop('badges', 0)
        a = uber.models.Attendee(_defer_defaults_=True, **d)
        a.name = d['name'] = name
        a.badges = d['badges'] = badges

        return a

    @classmethod
    def get(cls, payment_id):
        charge = cherrypy.session.pop(payment_id, None)
        if charge:
            return cls(**charge)
        else:
            raise HTTPRedirect('../preregistration/credit_card_retry')

    @classmethod
    def create_new_receipt(cls, model, create_model=False, items=None):
        """
        Iterates through the cost_calculations for this model and returns a list containing all non-null cost and credit items.
        This function is for use with new models to grab all their initial costs for creating or previewing a receipt.
        """
        from uber.models import AdminAccount, ModelReceipt, ReceiptItem
        if not items:
            items = [uber.receipt_items.cost_calculation.items] + [uber.receipt_items.credit_calculation.items]
        receipt_items = []
        receipt = ModelReceipt(owner_id=model.id, owner_model=model.__class__.__name__) if create_model else None
        
        for i in items:
            for calculation in i[model.__class__.__name__].values():
                item = calculation(model)
                if item:
                    try:
                        desc, cost, count = item
                    except ValueError:
                        # Unpack list of wrong size (no quantity provided).
                        desc, cost = item
                        count = 1
                    if isinstance(cost, Iterable):
                        # A list of the same item at different prices, e.g., group badges
                        for price in cost:
                            if receipt:
                                receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                                desc=desc,
                                                                amount=price,
                                                                count=cost[price],
                                                                who=AdminAccount.admin_name() or 'non-admin'
                                                                ))
                            else:
                                receipt_items.append((desc, price, cost[price]))
                    elif receipt:
                        receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                          desc=desc,
                                                          amount=cost,
                                                          count=count,
                                                          who=AdminAccount.admin_name() or 'non-admin'
                                                        ))
                    else:
                        receipt_items.append((desc, cost, count))
        
        return receipt, receipt_items

    @classmethod
    def calc_simple_cost_change(cls, model, col_name, new_val):
        """
        Takes an instance of a model and attempts to calculate a simple cost change
        based on a column name. Used for columns where the cost is the column, e.g.,
        extra_donation and amount_extra.
        """
        model_dict = model.to_dict()

        if model_dict.get(col_name) == None:
            return None, None
        
        if not new_val:
            new_val = 0
        
        return (model_dict[col_name] * 100, (int(new_val) - model_dict[col_name]) * 100)

    @classmethod
    def process_receipt_credit_change(cls, model, col_name, new_val, receipt=None):
        from uber.models import AdminAccount, ReceiptItem

        credit_change_tuple = model.credit_changes.get(col_name)
        if credit_change_tuple:
            credit_change_name = credit_change_tuple[0]
            credit_change_func = credit_change_tuple[1]

            change_func = getattr(model, credit_change_func)
            old_discount, discount_change = change_func(**{col_name: new_val})
            if old_discount >= 0 and discount_change < 0:
                verb = "Added"
            elif old_discount < 0 and discount_change >= 0 and old_discount == discount_change * -1:
                verb = "Removed"
            else:
                verb = "Changed"
            discount_desc = "{} {}".format(credit_change_name, verb)
            
            if col_name == 'birthdate':
                old_val = datetime.strftime(getattr(model, col_name), c.TIMESTAMP_FORMAT)
            else:
                old_val = getattr(model, col_name)

            if receipt:
                return ReceiptItem(receipt_id=receipt.id,
                                   desc=discount_desc,
                                   amount=discount_change,
                                   who=AdminAccount.admin_name() or 'non-admin',
                                   revert_change={col_name: old_val},
                                )
            else:
                return (discount_desc, discount_change)

    @classmethod
    def process_receipt_upgrade_item(cls, model, col_name, new_val, receipt=None, count=1):
        """
        Finds the cost of a receipt item to add to an existing receipt.
        This uses the cost_changes dictionary defined on each model in receipt_items.py,
        calling it with the extra keyword arguments provided. If no function is specified,
        we use calc_simple_cost_change instead.
        
        If a ModelReceipt is provided, a new ReceiptItem is created and returned.
        Otherwise, the raw values are returned so attendees can preview their receipt 
        changes.
        """
        from uber.models import AdminAccount, ReceiptItem
        from uber.models.types import Choice

        try:
            new_val = int(new_val)
        except Exception:
            pass # It's fine if this is not a number

        if col_name != 'badges' and isinstance(model.__table__.columns.get(col_name).type, Choice):
            increase_term, decrease_term = "Upgrading", "Downgrading"
        else:
            increase_term, decrease_term = "Increasing", "Decreasing"

        cost_change_tuple = model.cost_changes.get(col_name)
        if not cost_change_tuple:
            cost_change_name = col_name.replace('_', ' ').title()
            old_cost, cost_change = cls.calc_simple_cost_change(model, col_name, new_val)
        else:
            cost_change_name = cost_change_tuple[0]
            cost_change_func = cost_change_tuple[1]
            if len(cost_change_tuple) > 2:
                cost_change_name = cost_change_name.format(*[dictionary.get(new_val, str(new_val)) for dictionary in cost_change_tuple[2:]])
            
            if not cost_change_func:
                old_cost, cost_change = cls.calc_simple_cost_change(model, col_name, new_val)
            else:
                change_func = getattr(model, cost_change_func)
                old_cost, cost_change = change_func(**{col_name: new_val})

        is_removable_item = col_name != 'badge_type'
        if not old_cost and is_removable_item:
            cost_desc = "Adding {}".format(cost_change_name)
        elif cost_change * -1 == old_cost and is_removable_item: # We're crediting the full amount of the item
            cost_desc = "Removing {}".format(cost_change_name)
        elif cost_change > 0:
            cost_desc = "{} {}".format(increase_term, cost_change_name)
        else:
            cost_desc = "{} {}".format(decrease_term, cost_change_name)

        if col_name == 'tables':
            old_val = int(getattr(model, col_name))
        else:
            old_val = getattr(model, col_name)

        if receipt:
            return ReceiptItem(receipt_id=receipt.id,
                                desc=cost_desc,
                                amount=cost_change,
                                count=count,
                                who=AdminAccount.admin_name() or 'non-admin',
                                revert_change={col_name: old_val},
                            )
        else:
            return (cost_desc, cost_change, count)

    def prereg_receipt_preview(self):
        """
        Returns a list of tuples where tuple[0] is the name of a group of items,
        and tuple[1] is a list of cost item tuples from create_new_receipt
        
        This lets us show the attendee a nice display of what they're buying
        ... whenever we get around to actually using it that way
        """
        from uber.models import PromoCodeGroup

        items_preview = []
        for model in self.models:
            if getattr(model, 'badges', None) and getattr(model, 'name') and isinstance(model, uber.models.Attendee):
                items_group = ("{} plus {} badges ({})".format(getattr(model, 'full_name', None), int(model.badges) - 1, model.name), [])
                x, receipt_items = Charge.create_new_receipt(PromoCodeGroup())
            else:
                group_name = getattr(model, 'name', None)
                items_group = (group_name or getattr(model, 'full_name', None), [])
            
            x, receipt_items = Charge.create_new_receipt(model)
            items_group[1].extend(receipt_items)
            
            items_preview.append(items_group)

        return items_preview

    def set_total_cost(self):
        preview_receipt_groups = self.prereg_receipt_preview()
        for group in preview_receipt_groups:
            self._current_cost += sum([(item[1] * item[2]) for item in group[1]])

    @property
    def has_targets(self):
        return not not self._targets

    @cached_property
    def total_cost(self):
        return self._current_cost

    @cached_property
    def dollar_amount(self):
        return self.total_cost // 100

    @cached_property
    def description(self):
        return self._description or self.names

    @cached_property
    def receipt_email(self):
        email = self.models[0].email if self.models and self.models[0].email else self._receipt_email
        return email[0] if isinstance(email, list) else email  

    @cached_property
    def names(self):
        names = []

        for m in self.models:
            if getattr(m, 'badges', None) and getattr(m, 'name') and isinstance(m, uber.models.Attendee):
                names.append("{} plus {} badges ({})".format(getattr(m, 'full_name', None), int(m.badges) - 1, m.name))
            else:
                group_name = getattr(m, 'name', None)
                names.append(group_name or getattr(m, 'full_name', None))

        return ', '.join(names)

    @cached_property
    def targets(self):
        return self.to_sessionized(self._targets)

    @cached_property
    def models(self):
        return self.from_sessionized(self._targets)

    @cached_property
    def attendees(self):
        return [m for m in self.models if isinstance(m, uber.models.Attendee)]

    @cached_property
    def groups(self):
        return [m for m in self.models if isinstance(m, uber.models.Group)]

    def create_stripe_intent(self, amount=0, receipt_email='', description=''):
        """
        Creates a Stripe Intent, which is what Stripe uses to process payments.
        After calling this, call create_receipt_transaction with the Stripe Intent's ID
        and the receipt to add the new transaction to the receipt.
        """
        from uber.custom_tags import format_currency

        amount = amount or self.total_cost
        receipt_email = receipt_email or self.receipt_email
        description = description or self.description

        if not amount or amount <= 0:
            log.error('Was asked for a Stripe Intent but the currently owed amount is invalid: {}'.format(amount))
            return "There was an error calculating the amount. Please refresh the page or contact the system admin."

        if amount > 999999:
            return "We cannot charge {}. Please make sure your total is below $9,999.".format(format_currency(amount / 100))

        log.debug('Creating Stripe Intent to charge {} cents for {}', amount, description)
        try:
            return self.stripe_or_authorize_intent(amount, description, receipt_email)
        except Exception as e:
            error_txt = 'Got an error while calling create_stripe_intent()'
            report_critical_exception(msg=error_txt, subject='ERROR: MAGFest Stripe invalid request error')
            return 'An unexpected problem occurred while setting up payment: ' + str(e)
        
    def stripe_or_authorize_intent(self, amount, description, receipt_email):
        if c.AUTHORIZENET_LOGIN_ID:
            return MockStripeIntent(
                amount=int(amount),
                description=description,
                receipt_email=receipt_email
            )
        else:
            customer = None
            if receipt_email:
                customer_list = stripe.Customer.list(
                    email=receipt_email,
                    limit=1,
                )
                if customer_list:
                    customer = customer_list.data[0]
                else:
                    customer = stripe.Customer.create(
                        description=receipt_email,
                        email=receipt_email,
                    )

            return stripe.PaymentIntent.create(
                payment_method_types=['card'],
                amount=int(amount),
                currency='usd',
                description=description,
                receipt_email=customer.email if receipt_email else None,
                customer=customer.id if customer else None,
            )
    
    @classmethod
    def send_authorizenet_txn(self, ref_id, amount, desc="", token_dict={}, txn_type=c.AUTHCAPTURE):
        from authorizenet import apicontractsv1, apicontrollers
        from decimal import Decimal
        
        merchantAuth = apicontractsv1.merchantAuthenticationType()
        merchantAuth.name = c.AUTHORIZENET_LOGIN_ID
        merchantAuth.transactionKey = c.AUTHORIZENET_LOGIN_KEY
        
        transaction = apicontractsv1.transactionRequestType()

        if token_dict:
            opaqueData = apicontractsv1.opaqueDataType()
            opaqueData.dataDescriptor = token_dict["desc"]
            opaqueData.dataValue = token_dict["val"]

            paymentInfo = apicontractsv1.paymentType()
            paymentInfo.opaqueData = opaqueData
            transaction.payment = paymentInfo

        if desc:
            order = apicontractsv1.orderType()
            order.description = desc
            transaction.order = order

        transaction.transactionType = c.AUTHNET_TXN_TYPES[txn_type]
        transaction.amount = Decimal(int(amount) / 100)

        transactionRequest = apicontractsv1.createTransactionRequest()
        transactionRequest.merchantAuthentication = merchantAuth
        transactionRequest.transactionRequest = transaction
        
        # Create the controller and get response
        transactionController = apicontrollers.createTransactionController(transactionRequest)
        transactionController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        transactionController.execute()

        response = transactionController.getresponse()

        if response is not None:
        # Check to see if the API request was successfully received and acted upon
            if response.messages.resultCode == "Ok":
                # Since the API request was successful, look for a transaction response
                # and parse it to display the results of authorizing the card
                if hasattr(response.transactionResponse, 'messages') == True:
                    auth_txn_id = int(response.transactionResponse.transId)
                    
                    print ('Successfully created transaction with Transaction ID: %s' % auth_txn_id)
                    print ('Transaction Response Code: %s' % response.transactionResponse.responseCode)
                    print ('Message Code: %s' % response.transactionResponse.messages.message[0].code)
                    print ('Auth Code: %s' % response.transactionResponse.authCode)
                    print ('Description: %s' % response.transactionResponse.messages.message[0].description)
                    
                    if txn_type in [c.AUTHCAPTURE, c.CAPTURE]:
                        self.mark_paid_from_intent_id(ref_id, auth_txn_id)
                    elif txn_type == c.AUTHONLY:
                        return auth_txn_id
                    elif txn_type == c.REFUND:
                        pass
                    return
                else:
                    report_critical_exception(msg="{} {}".format(
                        str(response.transactionResponse.errors.error[0].errorCode),
                        response.transactionResponse.errors.error[0].errorText
                    ), subject='ERROR: Authorize.net error')

                    return response.transactionResponse.errors.error[0].errorText
            # Or, print errors if the API request wasn't successful
            else:
                if hasattr(response, 'transactionResponse') == True and hasattr(response.transactionResponse, 'errors') == True:
                    error_code = str(response.transactionResponse.errors.error[0].errorCode)
                    error_msg = response.transactionResponse.errors.error[0].errorText
                else:
                    error_code = response.messages.message[0]['code'].text
                    error_msg = response.messages.message[0]['text'].text
                    
                report_critical_exception(msg="{} {}".format(error_code, error_msg), subject='ERROR: Authorize.net error')
                    
                return error_msg
        else:
            return "No response???"


    @classmethod
    def create_receipt_transaction(self, receipt, desc='', intent_id='', amount=0, method=c.STRIPE):
        txn_total = amount
        
        if intent_id and not c.AUTHORIZENET_LOGIN_ID:
            intent = stripe.PaymentIntent.retrieve(intent_id)
            txn_total = intent.amount
            if not amount:
                amount = txn_total
        
        if amount <= 0:
            return "There was an issue recording your payment."

        return uber.models.ReceiptTransaction(
            receipt_id=receipt.id,
            intent_id=intent_id,
            amount=amount,
            txn_total=txn_total or amount,
            receipt_items=receipt.open_receipt_items,
            desc=desc,
            method=method,
            who=uber.models.AdminAccount.admin_name() or 'non-admin'
        )

    @staticmethod
    def update_refunded_from_stripe(intent_id, total_refund, preferred_txn=None):
        from uber.models import Session

        refund_left = total_refund

        session = Session()
        matching_txns = session.query(uber.models.ReceiptTransaction).filter_by(intent_id=intent_id).all()

        current_total = sum([txn.refunded for txn in matching_txns])
        if current_total == total_refund:
            session.close()
            return

        if preferred_txn:
            preferred_txn.refunded = min(preferred_txn.amount, total_refund - current_total + preferred_txn.refunded)
            refund_left = total_refund - current_total - preferred_txn.amount_left
            session.add(preferred_txn)
            if not refund_left:
                session.commit()
                session.close()
                return preferred_txn

        for txn in matching_txns:
            txn.refunded = min(txn.amount, refund_left)
            session.add(txn)

            refund_left = refund_left - txn.amount
            if not refund_left:
                session.commit()
                session.close()
                return matching_txns


    @staticmethod
    def mark_paid_from_intent_id(intent_id, charge_id):
        from uber.models import Attendee, ArtShowApplication, MarketplaceApplication, Group, Session
        from uber.tasks.email import send_email
        from uber.decorators import render
        
        session = Session().session
        matching_txns = session.query(uber.models.ReceiptTransaction).filter_by(intent_id=intent_id).filter(
                                                                        uber.models.ReceiptTransaction.charge_id == '').all()

        for txn in matching_txns:
            txn.charge_id = charge_id
            session.add(txn)
            txn_receipt = txn.receipt

            for item in txn.receipt_items:
                item.closed = datetime.now()
                session.add(item)

            session.commit()

            model = session.get_model_by_receipt(txn_receipt)
            if isinstance(model, Attendee) and model.is_paid:
                if model.badge_status == c.PENDING_STATUS:
                    model.badge_status = c.NEW_STATUS
                if model.paid in [c.NOT_PAID, c.PENDING]:
                    model.paid = c.HAS_PAID
            if isinstance(model, Group) and model.is_paid:
                model.paid = c.HAS_PAID
            session.add(model)

            session.commit()

            if model and isinstance(model, Group) and model.is_dealer and not txn.receipt.open_receipt_items:
                try:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        c.MARKETPLACE_EMAIL,
                        '{} Payment Completed'.format(c.DEALER_TERM.title()),
                        render('emails/dealers/payment_notification.txt', {'group': model}, encoding=None),
                        model=model.to_dict('id'))
                except Exception:
                    log.error('Unable to send {} payment confirmation email'.format(c.DEALER_TERM), exc_info=True)
            if model and isinstance(model, ArtShowApplication) and not txn.receipt.open_receipt_items:
                try:
                    send_email.delay(
                        c.ART_SHOW_EMAIL,
                        c.ART_SHOW_EMAIL,
                        'Art Show Payment Received',
                        render('emails/art_show/payment_notification.txt',
                            {'app': model}, encoding=None),
                        model=model.to_dict('id'))
                except Exception:
                    log.error('Unable to send Art Show payment confirmation email', exc_info=True)
            if model and isinstance(model, MarketplaceApplication) and not txn.receipt.open_receipt_items:
                send_email.delay(
                    c.MARKETPLACE_APP_EMAIL,
                    c.MARKETPLACE_APP_EMAIL,
                    'Marketplace Payment Received',
                    render('emails/marketplace/payment_notification.txt',
                        {'app': model}, encoding=None),
                    model=model.to_dict('id'))
                send_email.delay(
                    c.MARKETPLACE_APP_EMAIL,
                    model.email_to_address,
                    'Marketplace Payment Received',
                    render('emails/marketplace/payment_confirmation.txt',
                        {'app': model}, encoding=None),
                    model=model.to_dict('id'))

        session.close()
        return matching_txns