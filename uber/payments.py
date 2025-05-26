import checkdigit.verhoeff as verhoeff
import pytz
from typing import Iterable
from collections import OrderedDict
from datetime import datetime, timedelta
from dateutil.parser import parse
from uuid import uuid4

import cherrypy
import requests
import stripe

from authorizenet import apicontractsv1, apicontrollers
from pockets import cached_property, classproperty, is_listy, listify
from pockets.autolog import log

import uber
from uber.config import c
from uber.custom_tags import format_currency, email_only
from uber.utils import report_critical_exception
import uber.spin_rest_utils as spin_rest_utils

class MockStripeIntent(dict):
    """
    Stripe and Authorize.net use radically different workflows: Stripe has you request a payment intent
    before it collects CC details, and Authorize.net requires CC details (or a token) before it will
    do anything.

    We prefer Stripe's method as this creates a record in our system before payment is attempted in
    case anything goes wrong. This class lets us use Stripe's workflow in our page handlers with
    minimal disruptions.
    """
    def __init__(self, amount, description, receipt_email='', customer_id='', intent_id=''):
        self.id = intent_id or str(uuid4()).replace('-', '')[:20]
        self.amount = amount
        self.description = description
        self.receipt_email = receipt_email
        self.customer_id = customer_id
        self.charges = None

        # And now for the serializable info!
        dict.__init__(self, id=self.id, amount=amount, description=description, receipt_email=receipt_email,
                      customer_id=customer_id, charges=self.charges)


class PreregCart:
    """
    During preregistration, attendees and groups are not added to the database until
    the payment process is started. This class helps manage them in the session instead.
    """
    def __init__(self, targets=()):
        self._targets = listify(targets)
        self._current_cost = 0

    @classproperty
    def session_keys(cls):
        return ['paid_preregs', 'unpaid_preregs', 'pending_preregs', 'pending_dealers',
                'payment_intent_id', 'universal_promo_codes']

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
    def pending_dealers(cls):
        return cherrypy.session.setdefault('pending_dealers', OrderedDict())

    @classproperty
    def payment_intent_id(cls):
        return cherrypy.session.get('payment_intent_id', '')

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
    def to_sessionized(cls, m, **params):
        from uber.models import Attendee, Group
        if is_listy(m):
            return [cls.to_sessionized(t) for t in m]
        elif isinstance(m, dict):
            return m
        elif isinstance(m, Attendee):
            d = m.to_dict(
                Attendee.to_dict_default_attrs
                + ['promo_code']
                + ['group_id']
                + list(Attendee._extra_apply_attrs_restricted))
            for key in params:
                if params.get(key):
                    d[key] = params.get(key)
            return d
        elif isinstance(m, Group):
            d = m.to_dict(
                Group.to_dict_default_attrs
                + ['attendees']
                + list(Group._extra_apply_attrs_restricted))
            for key in params:
                if params.get(key):
                    d[key] = params.get(key)
            return d
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
        badge_count = d.pop('badge_count', 0)
        g = uber.models.Group(_defer_defaults_=True, **d)
        g.badge_count = d['badge_count'] = badge_count
        return g

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

    @property
    def has_targets(self):
        return not not self._targets
    
    @property
    def purchaser(self):
        """
        Attempt to figure out which models to assign as the 'purchaser' for PreregCart.receipt_email
        and the purchaser_id on all ReceiptItem generated by this cart.
        Note that if attendee accounts are enabled, PreregCart.receipt_email is not used.

        Note: This does not account for groups as we no longer actually sell groups via prereg.
        """
        from uber.models import Session
        from uber.utils import get_age_from_birthday
        if not self.models:
            return
        maybe_purchasers = []
        target_email = None

        for model in self.models:
            if get_age_from_birthday(model.birthdate, c.NOW_OR_AT_CON) >= 18:
                maybe_purchasers.append(model)
        
        maybe_purchasers = maybe_purchasers or [m for m in self.models]

        if c.ATTENDEE_ACCOUNTS_ENABLED:
            with Session() as session:
                target_email = session.current_attendee_account().email

            for purchaser in maybe_purchasers:
                if purchaser.email == target_email:
                    return purchaser

        return maybe_purchasers[0]

    @cached_property
    def description(self):
        names = []

        for m in self.models:
            if getattr(m, 'badges', None) and getattr(m, 'name') and isinstance(m, uber.models.Attendee):
                names.append("{} plus {} badges ({})".format(getattr(m, 'full_name', None), int(m.badges) - 1, m.name))
            else:
                group_name = getattr(m, 'name', None)
                attendee_name = getattr(m, 'full_name', None)
                badge_name = getattr(m, 'badge_printed_name', None)
                if attendee_name and badge_name:
                    attendee_name = attendee_name + f" ({badge_name})"
                names.append(group_name or attendee_name)

        return ', '.join(names)

    @cached_property
    def receipt_email(self):
        email = self.purchaser.email if self.purchaser and self.purchaser.email else ''
        return email[0] if isinstance(email, list) else email

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

    def set_total_cost(self):
        preview_receipt_groups = self.prereg_receipt_preview()
        for group in preview_receipt_groups:
            self._current_cost += sum([(item[1] * item[2]) for item in group[1]])

    @cached_property
    def total_cost(self):
        return self._current_cost

    @cached_property
    def dollar_amount(self):
        return self.total_cost // 100

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
                items_group = (f"{getattr(model, 'full_name', None)} plus "
                               f"{int(model.badges) - 1} badges ({model.name})", [])
                x, receipt_items = ReceiptManager.create_new_receipt(PromoCodeGroup(), purchaser_id=self.purchaser.id)
            else:
                group_name = getattr(model, 'name', None)
                items_group = (group_name or getattr(model, 'full_name', None), [])

            x, receipt_items = ReceiptManager.create_new_receipt(model, purchaser_id=self.purchaser.id)
            items_group[1].extend(receipt_items)

            items_preview.append(items_group)

        return items_preview


class TransactionRequest:
    # TODO: Split out Stripe and AuthNet logic into their own subclasses, like SpinTerminalRequest
    def __init__(self, receipt=None, receipt_email='', description='', amount=0,
                 method=c.STRIPE, customer_id=None, **kwargs):
        self.amount = int(amount)
        self.receipt_email = receipt_email[0] if isinstance(receipt_email, list) else receipt_email
        self.description = description
        self.customer_id = customer_id
        self.refund_str = "refunded"  # Set to "voided" when applicable to better inform admins
        self.intent, self.response, self.receipt_manager = None, None, None
        self.method = method
        self.tracking_id = str(uuid4())

        log.debug(f"Transaction {self.tracking_id} started with {amount} amount, {receipt_email} "
                  f"receipt email, {description} description, and {customer_id} customer ID.")

        if receipt:
            log.debug(f"Transaction {self.tracking_id} initialized with receipt id {receipt.id}, "
                      f"which has {receipt.current_amount_owed} balance due.")
            self.receipt_manager = ReceiptManager(receipt)

            if 'who' in kwargs:
                self.receipt_manager.who = kwargs['who']

            if not self.amount:
                self.amount = receipt.current_amount_owed

        if c.AUTHORIZENET_LOGIN_ID:
            self.merchant_auth = apicontractsv1.merchantAuthenticationType(
                name=c.AUTHORIZENET_LOGIN_ID,
                transactionKey=c.AUTHORIZENET_LOGIN_KEY
            )

    @property
    def response_id(self):
        if not self.response:
            return
        if c.AUTHORIZENET_LOGIN_ID:
            return self.response.transId
        else:
            return self.response.id

    @cached_property
    def dollar_amount(self):
        from decimal import Decimal
        return Decimal(int(self.amount)) / Decimal(100)

    def get_receipt_items_to_add(self):
        if not self.receipt_manager:
            return
        items_to_add = self.receipt_manager.items_to_add
        self.receipt_manager.items_to_add = []
        return items_to_add

    def create_stripe_intent(self, intent_id=''):
        """
        Creates a Stripe Intent, which is what Stripe uses to process payments.
        After calling this, call create_payment_transaction with the Stripe Intent object
        and the receipt to add the new transaction to the receipt.
        """

        if not self.amount or self.amount <= 0:
            log.error('Was asked for a Stripe Intent but the currently owed amount is invalid: {}'.format(self.amount))
            return "There was an error calculating the amount. Please refresh the page or contact the system admin."

        if self.amount > 999999:
            return (f"We cannot charge {format_currency(self.amount / 100)}. "
                    "Please make sure your total is below $9,999.")
        try:
            self.intent = self.stripe_or_mock_intent(intent_id)
        except Exception as e:
            error_txt = 'Got an error while creating a Stripe intent for transaction {self.tracking_id}'
            report_critical_exception(msg=error_txt, subject='ERROR: MAGFest Stripe invalid request error')
            return 'An unexpected problem occurred while setting up payment: ' + str(e)

    def stripe_or_mock_intent(self, intent_id=''):
        if not self.customer_id:
            self.get_or_create_customer()

        if c.AUTHORIZENET_LOGIN_ID or c.AT_THE_CON and c.SPIN_TERMINAL_AUTH_KEY:
            return MockStripeIntent(
                amount=self.amount,
                description=self.description,
                receipt_email=self.receipt_email,
                customer_id=self.customer_id,
                intent_id=intent_id
            )
        else:
            log.debug(f'Transaction {self.tracking_id}: creating Stripe Intent to charge '
                      f'{self.amount} cents for {self.description}')

            return stripe.PaymentIntent.create(
                payment_method_types=['card'],
                amount=self.amount,
                currency='usd',
                description=self.description,
                receipt_email=self.receipt_email,
                customer=self.customer_id,
            )

    def stripe_or_authnet_refund(self, txn, amount):
        if c.AUTHORIZENET_LOGIN_ID:
            error = self.get_authorizenet_txn(txn.charge_id)

            if error:
                return error

            if self.response.transactionStatus == "capturedPendingSettlement":
                if amount != int(self.response.authAmount * 100):
                    return "This transaction cannot be partially refunded until it's settled."
                self.refund_str = "voided"
                error = self.send_authorizenet_txn(txn_type=c.VOID, txn_id=txn.charge_id)
            elif self.response.transactionStatus != "settledSuccessfully":
                return ("This transaction cannot be refunded because of an invalid status: "
                        f"{self.response.transactionStatus}.")
            else:
                if parse(str(self.response.submitTimeUTC)).replace(tzinfo=pytz.UTC) \
                        < datetime.now(pytz.UTC) - timedelta(days=180):
                    return "This transaction is more than 180 days old and cannot be refunded automatically."

                if self.response.settleAmount * 100 < self.amount:
                    return "This transaction was only for {} so it cannot be refunded {}.".format(
                        format_currency(self.response.settleAmount),
                        format_currency(self.amount / 100))
                cc_num = str(self.response.payment.creditCard.cardNumber)[-4:]
                zip = str(self.response.billTo.zip)
                error = self.send_authorizenet_txn(txn_type=c.REFUND, amount=amount, cc_num=cc_num,
                                                   zip=zip, txn_id=txn.charge_id)
            if error:
                return 'An unexpected problem occurred: ' + str(error)
        else:
            try:
                self.response = stripe.Refund.create(payment_intent=txn.intent_id,
                                                     amount=amount,
                                                     reason='requested_by_customer')
            except Exception as e:
                error_txt = 'Error while refunding via Stripe' \
                            '(self, stripeID={!r})'.format(txn.stripe_id)
                report_critical_exception(
                    msg=error_txt,
                    subject='ERROR: MAGFest Stripe invalid request error')
                return 'An unexpected problem occurred: ' + str(e)

    def refund_or_cancel(self, txn, department=None):
        if not self.amount:
            return "You must enter an amount to refund."

        error = self._pre_process_refund(txn)
        if not error:
            error = self._process_refund(txn, department=department)

        if error:
            return error

    def refund_or_skip(self, txn, department=None):
        if not self.amount:
            return "You must enter an amount to refund."

        error = self._pre_process_refund(txn)
        if error:
            return

        error = self._process_refund(txn, department=department)

        if error:
            return error

    def _pre_process_refund(self, txn):
        """
        Performs error checks and updates transactions to prepare them for _process_refund.
        This is split out from _process_refund because sometimes we want to skip transactions
        that can't be refunded and other times we want to cancel if we find an issue.
        """

        if not txn.intent_id:
            return "Can't refund a transaction that is not a Stripe payment."

        error = txn.check_stripe_id()
        if error:
            return "Error issuing refund: " + str(error)

        if not txn.charge_id:
            charge_id = txn.check_paid_from_stripe()
            if not charge_id:
                return "We could not find record of this payment being completed."

        already_refunded, last_refund_id = txn.update_amount_refunded()
        if txn.amount - already_refunded <= 0:
            return "This payment has already been fully refunded."

        refund_amount = int(self.amount or (txn.amount - already_refunded))
        if txn.amount - already_refunded < refund_amount:
            return "There is not enough left on this transaction to refund {format_currency(refund_amount / 100)}."

    def _process_refund(self, txn, department=None):
        """
        Attempts to refund a given Stripe transaction and add/update the relevant transactions on the receipt.
        Returns an error message or sets the object's response property if the refund was successful.
        """
        if not self.receipt_manager:
            log.error("ERROR: _process_refund was called using an object without a receipt; "
                      "we can't save anything that way!")
            return "There was an issue recording your refund. Please contact the developer."

        refund_amount = self.amount or txn.amount_left

        log.debug('REFUND: attempting to refund card transaction with ID {} {} cents for {}',
                  txn.stripe_id, str(refund_amount), txn.desc)

        message = self.stripe_or_authnet_refund(txn, int(refund_amount))
        if message:
            return message

        self.receipt_manager.create_refund_transaction(txn,
                                                       "Automatic refund of transaction " + txn.stripe_id,
                                                       str(self.response_id),
                                                       self.amount,
                                                       method=self.method,
                                                       department=department)
        self.receipt_manager.update_transaction_refund(txn, self.amount)

    def prepare_payment(self, intent_id='', payment_method=c.STRIPE, department=None):
        """
        Creates the stripe intent and receipt transaction for a given payment processor object.
        Most methods should call this instead of calling create_stripe_intent and
        create_payment_transaction directly.
        """
        if not self.receipt_manager:
            log.error("ERROR: prepare_payment was called using an object without a receipt; "
                      "we can't save anything that way!")
            return "There was an issue recording your payment. Please contact the developer."

        message = self.create_stripe_intent(intent_id)
        if not message:
            message = self.receipt_manager.create_payment_transaction(self.description, self.intent,
                                                                      method=payment_method,
                                                                      department=department)

        if message:
            return message

    def get_or_create_customer(self, customer_id=''):
        if not self.receipt_email:
            return

        if c.AUTHORIZENET_LOGIN_ID:
            log.debug(f"Transaction {self.tracking_id} getting or creating a customer with ID "
                      f"{customer_id} and email {self.receipt_email}")
            getCustomerRequest = apicontractsv1.getCustomerProfileRequest()
            getCustomerRequest.merchantAuthentication = self.merchant_auth
            if customer_id:
                getCustomerRequest.customerProfileId = customer_id
            else:
                getCustomerRequest.email = self.receipt_email
            getCustomerRequestController = apicontrollers.getCustomerProfileController(getCustomerRequest)
            getCustomerRequestController.setenvironment(c.AUTHORIZENET_ENDPOINT)
            getCustomerRequestController.execute()

            response = getCustomerRequestController.getresponse()
            if response is not None:
                if response.messages.resultCode == "Ok" and hasattr(response, 'profile') is True:
                    self.customer_id = str(response.profile.customerProfileId)
                    log.debug(f"Transaction {self.tracking_id} retrieved customer {self.customer_id}")
                    if hasattr(response.profile, 'paymentProfiles') is True:
                        for paymentProfile in response.profile.paymentProfiles:
                            log.debug(f"Transaction {self.tracking_id} deleting payment profile ID "
                                      f"{str(paymentProfile.customerPaymentProfileId)} from customer "
                                      f"{self.customer_id}")
                            self.delete_authorizenet_payment_profile(str(paymentProfile.customerPaymentProfileId))
                elif response.messages.message.code == 'E00040':
                    log.debug(f"Transaction {self.tracking_id} did not find customer, creating a new one...")
                    createCustomerRequest = apicontractsv1.createCustomerProfileRequest()
                    createCustomerRequest.merchantAuthentication = self.merchant_auth
                    createCustomerRequest.profile = apicontractsv1.customerProfileType(email=self.receipt_email)

                    createCustomerRequestController = apicontrollers.createCustomerProfileController(
                        createCustomerRequest)
                    createCustomerRequestController.setenvironment(c.AUTHORIZENET_ENDPOINT)
                    createCustomerRequestController.execute()

                    response = createCustomerRequestController.getresponse()

                    if response and (response.messages.resultCode == "Ok"):
                        self.customer_id = str(response.customerProfileId)
                    elif not response:
                        log.error(f"Transaction {self.tracking_id} failed to create customer profile. "
                                  "No response received.")
                    else:
                        log.error(f"Transaction {self.tracking_id} failed to create customer profile. "
                                  f"{str(response.messages.message[0]['code'].text)}: "
                                  f"{str(response.messages.message[0]['text'].text)}")
                else:
                    log.error(f"Transaction {self.tracking_id} failed to retrieve customer profile. "
                              f"{str(response.messages.message[0]['code'].text)}: "
                              f"{str(response.messages.message[0]['text'].text)}")
            else:
                log.error("Failed to retrieve customer profile for AuthNet: no response received.")
            return

        if self.receipt_email:
            customer_list = stripe.Customer.list(
                email=self.receipt_email,
                limit=1,
            )
            if customer_list:
                customer = customer_list.data[0]
            else:
                customer = stripe.Customer.create(
                    description=self.receipt_email,
                    email=self.receipt_email,
                )
            self.customer_id = customer.id if customer else None

    def create_authorizenet_payment_profile(self, paymentInfo, first_name='', last_name=''):
        # There seems to be no way to directly associate customer profiles with transactions
        # Instead we need to create "payment profile", fill it with the token, use the
        # payment profile as payment
        #
        # I love technology

        log.debug(f"Transaction {self.tracking_id} creating a payment profile for customer {self.customer_id}")

        profile = apicontractsv1.customerPaymentProfileType()
        profile.payment = paymentInfo

        if first_name:
            billTo = apicontractsv1.customerAddressType()
            billTo.firstName = first_name
            billTo.lastName = last_name
            profile.billTo = billTo

        createCustomerPaymentRequest = apicontractsv1.createCustomerPaymentProfileRequest()
        createCustomerPaymentRequest.merchantAuthentication = self.merchant_auth
        createCustomerPaymentRequest.paymentProfile = profile
        createCustomerPaymentRequest.customerProfileId = self.customer_id

        createCustomerPaymentController = apicontrollers.createCustomerPaymentProfileController(
            createCustomerPaymentRequest)
        createCustomerPaymentController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        createCustomerPaymentController.execute()

        response = createCustomerPaymentController.getresponse()
        if (response.messages.resultCode == "Ok"):
            profileToCharge = apicontractsv1.customerProfilePaymentType()
            profileToCharge.customerProfileId = self.customer_id
            profileToCharge.paymentProfile = apicontractsv1.paymentProfile()
            profileToCharge.paymentProfile.paymentProfileId = str(response.customerPaymentProfileId)

            log.debug(f"Transaction {self.tracking_id} successfully created a payment profile (ID "
                      f"{str(response.customerPaymentProfileId)}) for customer {self.customer_id}")

            return profileToCharge
        else:
            log.error(f"Transaction {self.tracking_id} failed to create customer payment profile: "
                      f"{response.messages.message[0]['text'].text}")

    def delete_authorizenet_payment_profile(self, payment_profile_id):
        if not self.customer_id:
            return

        deleteCustomerPaymentProfile = apicontractsv1.deleteCustomerPaymentProfileRequest()
        deleteCustomerPaymentProfile.merchantAuthentication = self.merchant_auth
        deleteCustomerPaymentProfile.customerProfileId = self.customer_id
        deleteCustomerPaymentProfile.customerPaymentProfileId = payment_profile_id

        controller = apicontrollers.deleteCustomerPaymentProfileController(deleteCustomerPaymentProfile)
        controller.setenvironment(c.AUTHORIZENET_ENDPOINT)
        controller.execute()

        response = controller.getresponse()

        if (response.messages.resultCode != "Ok"):
            log.error(f"Failed to delete customer payment profile with customer profile id \
                      {deleteCustomerPaymentProfile.customerProfileId}: {response.messages.message[0]['text'].text}")

    def get_authorizenet_txn(self, txn_id):
        transaction = apicontractsv1.getTransactionDetailsRequest()
        transaction.merchantAuthentication = self.merchant_auth
        transaction.transId = txn_id

        transactionController = apicontrollers.getTransactionDetailsController(transaction)
        transactionController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        transactionController.execute()

        response = transactionController.getresponse()
        if response is not None:
            if response.messages.resultCode == apicontractsv1.messageTypeEnum.Ok:
                self.response = response.transaction
                log.debug(f"Transaction {self.tracking_id} requested and received {txn_id} from AuthNet.")
                return
            elif response.messages is not None:
                log.error(f"Transaction {self.tracking_id} requested {txn_id} from AuthNet but received an error: "
                          f"{response.messages.message[0]['code'].text}: {response.messages.message[0]['text'].text}")
                return ('Failed to get transaction details from AuthNet. '
                        f'{response.messages.message[0]["code"].text}: {response.messages.message[0]["text"].text}')

        return response

    def send_authorizenet_txn(self, txn_type=c.AUTHCAPTURE, **params):
        # TODO: We should probably split this out quite a bit, it's a mess

        payment_profile = None
        order = None
        intent_id = params.get('intent_id')

        params_str = [f"{name}: {params[name]}" for name in params]
        log.debug(f"Transaction {self.tracking_id} building an AuthNet transaction request, request type "
                  f"'{c.AUTHNET_TXN_TYPES[txn_type]}'. Params: {params_str}")

        transaction = apicontractsv1.transactionRequestType()

        if 'token_desc' in params or 'cc_num' in params:
            paymentInfo = apicontractsv1.paymentType()

            if 'token_desc' in params:
                opaqueData = apicontractsv1.opaqueDataType()
                opaqueData.dataDescriptor = params.get("token_desc")
                opaqueData.dataValue = params.get("token_val")
                paymentInfo.opaqueData = opaqueData

                if self.description and 'intent_id' in params:
                    order = apicontractsv1.orderType()
                    order.invoiceNumber = params.get('intent_id', '')
                    order.description = self.description
                    transaction.order = order

                if self.customer_id:
                    payment_profile = self.create_authorizenet_payment_profile(paymentInfo,
                                                                               params.get('first_name', ''),
                                                                               params.get('last_name', ''))
                    if not payment_profile:
                        return f"Could not complete payment. Please contact us at {email_only(c.REGDESK_EMAIL)}."

            elif 'cc_num' in params:
                # This is only for refunds, hence the lack of expiration date
                creditCard = apicontractsv1.creditCardType()
                creditCard.cardNumber = params.get("cc_num")
                creditCard.expirationDate = "XXXX"
                paymentInfo.creditCard = creditCard
                billTo = apicontractsv1.customerAddressType()
                billTo.zip = params.get("zip")
                transaction.billTo = billTo

            if payment_profile:
                transaction.profile = payment_profile
            else:
                transaction.payment = paymentInfo

        if 'txn_id' in params:
            transaction.refTransId = params.get("txn_id")

        if self.description and not order:
            order = apicontractsv1.orderType()
            order.description = self.description
            transaction.order = order

        transaction.transactionType = c.AUTHNET_TXN_TYPES[txn_type]
        transaction.customerIP = cherrypy.request.headers.get('X-Forwarded-For', cherrypy.request.remote.ip)

        if self.amount:
            transaction.amount = self.dollar_amount

        transactionRequest = apicontractsv1.createTransactionRequest()
        transactionRequest.merchantAuthentication = self.merchant_auth
        transactionRequest.transactionRequest = transaction

        transactionController = apicontrollers.createTransactionController(transactionRequest)
        transactionController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        transactionController.execute()

        response = transactionController.getresponse()

        txn_info = {}
        card_info = {}
        txn_info['fraud_info'] = {}
        txn_info['response'] = {}

        if response is not None:
            if response.messages.resultCode == "Ok":
                txn_response_dict = response.transactionResponse.__dict__

                txn_info['txn_id'] = str(txn_response_dict.get("transId", ''))
                txn_info['response']['response_code'] = txn_response_dict.get('responseCode', '')
                txn_info['response']['auth_code'] = txn_response_dict.get("authCode", '')
                txn_info['fraud_info']['avs'] = txn_response_dict.get("avsResultCode", '')
                txn_info['fraud_info']['cvv'] = txn_response_dict.get("cvvResultCode", '')
                txn_info['fraud_info']['cavv'] = txn_response_dict.get("cavvResultCode", '')

                card_info['CardType'] = str(txn_response_dict.get("accountType", ''))
                card_info['Last4'] = str(txn_response_dict.get('accountNumber', ''))

                if card_info['Last4']:
                    card_info['Last4'] = card_info['Last4'][4:]

                if hasattr(response.transactionResponse, 'messages') is True:
                    self.response = response.transactionResponse
                    auth_txn_id = str(self.response.transId)

                    txn_info['response']['message_code'] = str(response.transactionResponse.messages.message[0].code)
                    txn_info['response']['message'] = str(response.transactionResponse.messages.message[0].description)

                    log.debug(f"Transaction {self.tracking_id} request successful. Transaction ID: {auth_txn_id}")
                    self.log_authorizenet_response(intent_id, txn_info, card_info)

                    if txn_type in [c.AUTHCAPTURE, c.CAPTURE]:
                        ReceiptManager.mark_paid_from_ids(params.get('intent_id'), auth_txn_id)
                else:
                    txn_info['response']['message_code'] = str(response.transactionResponse.errors.error[0].errorCode)
                    txn_info['response']['message'] = str(response.transactionResponse.errors.error[0].errorText)
                    log.debug(f"Transaction {self.tracking_id} declined! "
                              f"{txn_info['response']['message_code']}: {txn_info['response']['message']}")
                    self.log_authorizenet_response(intent_id, txn_info, card_info)

                    return "Transaction declined. Please ensure you are entering the correct expiration date, card CVV/CVC, and ZIP Code."
            else:
                if hasattr(response, 'transactionResponse') is True \
                        and hasattr(response.transactionResponse, 'errors') is True:
                    txn_info['response']['message_code'] = str(response.transactionResponse.errors.error[0].errorCode)
                    txn_info['response']['message'] = str(response.transactionResponse.errors.error[0].errorText)
                else:
                    txn_info['response']['message_code'] = str(response.messages.message[0]['code'].text)
                    txn_info['response']['message'] = str(response.messages.message[0]['text'].text)

                log.error(f"Transaction {self.tracking_id} request failed! {txn_info['response']['message_code']}: {txn_info['response']['message']}")
                self.log_authorizenet_response(intent_id, txn_info, card_info)

                return "Transaction failed. Please refresh the page and try again, " + \
                    f"or contact us at {email_only(c.REGDESK_EMAIL)}."
        else:
            log.error(f"Transaction {self.tracking_id} request to AuthNet failed: no response received.")

    def log_authorizenet_response(self, intent_id, txn_info, card_info):
        from uber.models import ReceiptInfo, ReceiptTransaction, Session
        
        session = Session().session
        matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=intent_id).all()

        # AuthNet returns "StringElement" but we want strings
        txn_info['response'] = {key: str(val) for key, val in txn_info['response'].items()}
        txn_info['fraud_info'] = {key: str(val) for key, val in txn_info['fraud_info'].items()}

        if not matching_txns:
            log.debug(f"Tried to save receipt info for intent ID {intent_id} but we couldn't find any matching payments!")
        
        for txn in matching_txns:
            txn.receipt_info = ReceiptInfo(txn_info=txn_info, card_data=card_info, charged=datetime.now())
            session.add(txn.receipt_info)
        session.commit()


class SpinTerminalRequest(TransactionRequest):
    def __init__(self, terminal_id='', amount=0, capture_signature=None, tracker=None, spin_payment_type="Credit",
                 use_account_info=True, **kwargs):
        self.api_url = c.SPIN_TERMINAL_URL
        self.auth_key = c.SPIN_TERMINAL_AUTH_KEY
        self.timeout_retries = 0
        self.error_message = ""
        self.ref_id = ""  # This is the same as a transaction's intent ID.
        # TODO: integrate ref_id a bit better instead of swapping between intent.id and ref_id
        self.use_account_info = use_account_info

        self.terminal_id = terminal_id
        self.payment_type = spin_payment_type
        if tracker:
            self.tracker = tracker

        super().__init__(amount=amount, **kwargs)

        if capture_signature is None:
            self.capture_signature = False if self.amount < c.SPIN_TERMINAL_SIGNATURE_THRESHOLD else True
        else:
            self.capture_signature = capture_signature

    def get_or_create_customer(self, customer_id=''):
        self.customer_id = ''

    @property
    def base_request(self):
        return spin_rest_utils.base_request(self.terminal_id, self.auth_key)

    @property
    def sale_request_dict(self):
        return dict(spin_rest_utils.sale_request_dict(self.dollar_amount,
                                                      self.payment_type,
                                                      self.ref_id or (self.intent.id if self.intent else ''),
                                                      self.capture_signature), **self.base_request)

    def handle_api_call(f):
        from functools import wraps

        @wraps(f)
        def api_call(self, *args, **kwargs):
            try:
                return f(self, *args, **kwargs)
            except requests.exceptions.ConnectionError as e:
                log.error(f"Transaction {self.tracking_id} could not connect to SPIn Proxy: {str(e)}")
                self.error_message = "Could not connect to SPIn Proxy"
            except requests.exceptions.Timeout as e:
                if self.timeout_retries > 10:
                    log.error(f"Transaction {self.tracking_id} timed out while connecting to SPIn Terminal: {str(e)}")
                    self.error_message = "The request timed out"
                else:
                    self.timeout_retries += 1
            except requests.exceptions.RequestException as e:
                log.error(f"Transaction {self.tracking_id} errored while processing SPIn Terminal sale: {str(e)}")
                self.error_message = "Unexpected error"

        return api_call

    def retry_if_busy(self, func, *args, **kwargs):
        from time import sleep

        response = func(*args, **kwargs)
        while self.error_message_from_response(response.json()) == 'busy':
            response = func(*args, **kwargs)
            sleep(1)
        return response

    def error_message_from_response(self, response_json):
        return spin_rest_utils.error_message_from_response(response_json)

    def api_response_successful(self, response_json):
        return spin_rest_utils.api_response_successful(response_json)

    def log_api_response(self, response_json):
        import json

        if self.api_response_successful(response_json):
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id,
                               'last_response', json.dumps(response_json))
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id,
                               'last_error', '')
        else:
            error_message = self.error_message_from_response(response_json)
            log.error(f"Error while processing terminal sale for transaction {self.tracking_id}: {error_message}")
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id, 'last_error', error_message)

    def process_sale_response(self, session, response):
        from uber.models import ReceiptTransaction

        try:
            response_json = response.json()
        except AttributeError:
            response_json = response
        self.tracker.response = response_json
        self.tracker.resolved = datetime.utcnow()

        receipt_items_to_add = self.get_receipt_items_to_add()
        if receipt_items_to_add:
            session.add_all(receipt_items_to_add)
        session.commit()

        self.check_retry_sale(session, response_json)

        if not self.api_response_successful(response_json):
            self.log_api_response(response_json)
            return

        if self.capture_signature and not spin_rest_utils.signature_from_response(response_json) \
                and spin_rest_utils.insecure_entry_type(response_json):
            error_message = "Signature was skipped so transaction was voided. Please retry payment"
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id, 'last_error', error_message)
            self.tracker.internal_error = error_message

            void_response = self.send_void_txn()
            void_response_json = void_response.json()

            if self.tracker:
                self.tracker.response = void_response_json
                self.tracker.resolved = datetime.utcnow()

            self.log_api_response(void_response_json)
            if self.api_response_successful(void_response_json):
                matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=self.intent.id)
                model_receipt_info = {}
                for txn in matching_txns:
                    txn.cancelled = datetime.now()
                    session.add(txn)
                    txn.receipt_info = self.receipt_info_from_txn(session, txn, model_receipt_info, void_response_json)
            return

        self.process_successful_sale(session, response_json, self.intent.id)

    def process_successful_sale(self, session, response_json, intent_id):
        from uber.models import ReceiptTransaction
        from uber.tasks.registration import send_receipt_email
        from decimal import Decimal

        self.tracker.success = True

        approval_amount = Decimal(str(spin_rest_utils.approved_amount(response_json))) * 100  # don't @ me
        if approval_amount != self.amount and abs(approval_amount - self.amount) > 5:
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id,
                               'last_error', "Partial approval")

        matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=intent_id).all()
        if not matching_txns:
            error_message = "Payment was successful, but did not have any matching transactions"
            log.error(f"Error while processing terminal sale for transaction {self.tracking_id}: {error_message}")
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id, 'last_error', error_message)
            return

        running_total = approval_amount
        model_receipt_info = {}

        for txn in matching_txns:
            if txn.txn_total != approval_amount:
                if txn.amount == txn.txn_total:  # Single transaction, nothing complicated to do here
                    txn.amount = approval_amount
                else:
                    if running_total < txn.amount:
                        txn.amount = running_total
                    running_total -= txn.amount
                txn.txn_total = approval_amount
            if txn.amount == 0:
                session.delete(txn)
            else:
                txn.receipt_info = self.receipt_info_from_txn(session, txn, model_receipt_info, response_json)
                txn.cancelled = None
                session.add(txn)
                session.add(txn.receipt_info)

        session.commit()

        ReceiptManager.mark_paid_from_ids(intent_id, self.terminal_id + "-" + intent_id)

        for receipt_info in model_receipt_info.values():
            send_receipt_email.delay(receipt_info.id)

        self.log_api_response(response_json)

    def receipt_info_from_txn(self, session, txn, model_receipt_info, response_json):
        from uber.models import Attendee

        # We want only one ReceiptInfo object per attendee account or group
        # However, we need to extract the account or group from each transaction's receipt
        # So we track a list of unique models and either create a new ReceiptInfo object or assign the existing one
        model = session.get_model_by_receipt(txn.receipt)
        if isinstance(model, Attendee) and c.ATTENDEE_ACCOUNTS_ENABLED and model.managers and self.use_account_info:
            model = model.managers[0] or model
        model_name = model.__class__.__name__
        if (model_name, model.id) not in model_receipt_info:
            new_receipt_info = self.create_receipt_info(model_name, model.id, response_json)
            model_receipt_info[(model_name, model.id)] = new_receipt_info
        return model_receipt_info[(model_name, model.id)]

    def create_receipt_info(self, model_name, model_id, response_json):
        from uber.models import ReceiptInfo

        txn_info = spin_rest_utils.txn_info_from_response(response_json)
        if txn_info['amount'] == 0:
            txn_info['amount'] = self.amount

        ref_id, card_data, emv_data, receipt_html = spin_rest_utils.processed_response_info(response_json)

        return ReceiptInfo(
            fk_email_model=model_name,
            fk_email_id=model_id,
            terminal_id=self.terminal_id,
            reference_id=ref_id or self.ref_id or self.intent.id,
            card_data=card_data,
            charged=datetime.now(),
            txn_info=txn_info,
            emv_data=emv_data,
            signature=spin_rest_utils.signature_from_response(response_json),
            receipt_html=receipt_html
            )

    @handle_api_call
    def check_retry_sale(self, session, response_json):
        from uber.models import ReceiptTransaction, TxnRequestTracking

        if spin_rest_utils.no_retry_error(response_json):
            return
        session.commit()
        new_tracker = TxnRequestTracking(workstation_num=self.tracker.workstation_num,
                                         terminal_id=self.tracker.terminal_id,
                                         fk_id=self.tracker.fk_id,
                                         who=self.tracker.who)
        self.tracker = new_tracker
        new_intent_id = self.intent_id_from_txn_tracker(self.tracker)
        matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=self.intent.id)
        for txn in matching_txns:
            txn.intent_id = new_intent_id
            session.add(txn)
        session.commit()

        return self.retry_if_busy(self.send_sale_txn)

    @handle_api_call
    def send_void_txn(self):
        return requests.post(spin_rest_utils.get_call_url(self.api_url, 'void'), data=self.sale_request_dict)

    @handle_api_call
    def send_sale_txn(self):
        return requests.post(spin_rest_utils.get_call_url(self.api_url, 'sale'), data=self.sale_request_dict)

    @handle_api_call
    def send_return_txn(self):
        return requests.post(spin_rest_utils.get_call_url(self.api_url, 'return'), data=self.sale_request_dict)

    @handle_api_call
    def check_txn_status(self, intent_id=''):
        return requests.post(spin_rest_utils.get_call_url(self.api_url, 'status'), data=dict(
            spin_rest_utils.txn_status_request_dict(self.payment_type,
                                                    intent_id or self.ref_id or (self.intent.id if self.intent else '')
                                                    ), **self.base_request))

    @handle_api_call
    def close_out_terminal(self):
        response = requests.post(spin_rest_utils.get_call_url(self.api_url, 'settle'), data=self.base_request)
        return response

    def _process_refund(self, txn, department=None):
        from uber.models import TxnRequestTracking, AdminAccount, Session
        from uber.tasks.registration import process_terminal_sale

        if not self.receipt_manager:
            log.error("ERROR: _process_refund was called using an object without a receipt; "
                      "we can't save anything that way!")
            return "There was an issue recording your refund. Please contact the developer."

        if not txn.receipt_info:
            return f"Transaction {txn.id} has no SPIn receipt information."

        refund_amount = self.amount or txn.amount_left
        refund_error = ""

        if refund_amount != txn.txn_total and not cherrypy.session.get('reg_station'):
            return ("This is a partial refund, which requires a connected SPIn payment terminal. "
                    "Please set your workstation number and try again.")
        
        with Session() as session:
            model = session.get_model_by_receipt(txn.receipt)
            model_id = model.id

        log.debug('REFUND: attempting to refund card transaction with ID {} {} cents for {}',
                  txn.stripe_id, str(refund_amount), txn.desc)

        self.tracker = TxnRequestTracking(workstation_num=cherrypy.session.get('reg_station', '0'), fk_id=model_id,
                                          terminal_id=self.terminal_id, who=AdminAccount.admin_name())

        self.receipt_manager.items_to_add.append(self.tracker)

        refund_txn = self.receipt_manager.create_refund_transaction(txn,
                                                                    "Automatic refund of transaction " + txn.stripe_id,
                                                                    self.intent_id_from_txn_tracker(self.tracker),
                                                                    refund_amount,
                                                                    method=self.method,
                                                                    department=department)

        self.terminal_id = txn.receipt_info.terminal_id
        self.ref_id = txn.intent_id

        status_response = self.check_txn_status()
        status_response_json = status_response.json()
        status_error_message = self.error_message_from_response(status_response_json)
        if self.api_response_successful(status_response_json):
            # Not batched out yet, so first step is to void the transaction on the original terminal
            self.amount = txn.txn_total
            self.refund_str = "voided"

            void_response = self.retry_if_busy(self.send_void_txn)
            void_response_json = void_response.json()

            self.tracker.response = void_response_json
            self.tracker.resolved = datetime.now()

            if self.api_response_successful(void_response_json):
                txn.receipt_info.voided = datetime.now()
                self.tracker.success = True

                refund_txn.receipt_info = self.create_receipt_info(txn.receipt_info.fk_email_model,
                                                                   txn.receipt_info.fk_email_id,
                                                                   void_response_json)
                refund_txn.amount = txn.txn_total * -1

                self.receipt_manager.items_to_add.append(refund_txn.receipt_info)
                self.receipt_manager.update_transaction_refund(txn, self.amount)

                if refund_amount == txn.txn_total:
                    return
                else:
                    # This is a partial refund, so we now run a sale on the CURRENTLY connected terminal
                    with Session() as session:
                        error, terminal_id = session.get_assigned_terminal_id()

                    reg_station_id = cherrypy.session.get('reg_station', '')

                    if error:
                        payment_error = error
                    else:
                        c.REDIS_STORE.delete(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id)

                        process_terminal_sale(reg_station_id,
                                              terminal_id,
                                              model_id,
                                              description=f"Payment for partial refund of transaction {txn.charge_id}",
                                              amount=txn.txn_total - refund_amount)

                        payment_error = c.REDIS_STORE.hget(c.REDIS_PREFIX + 'spin_terminal_txns:' + terminal_id,
                                                           'last_error')
                    if payment_error:
                        refund_error = f"Void successful, but partial re-payment failed: {payment_error}"
            else:
                refund_error = ("Error while voiding transaction: "
                                f"{self.error_message_from_response(void_response_json)}")
        elif status_error_message not in ['Not found', 'No open batch']:
            self.tracker.response = status_response_json
            refund_error = f"Error while looking up transaction: {status_error_message}"
        else:
            # Batched out transaction, run a return on the currently connected terminal
            with Session() as session:
                error, terminal_id = session.get_assigned_terminal_id()

            if error:
                refund_error = f"Error while running return: {error}"
            else:
                # We're now a return request, not a void request, so we need to change our properties accordingly
                self.terminal_id = terminal_id
                self.tracker.terminal_id = terminal_id
                self.ref_id = refund_txn.refund_id
                self.amount = refund_amount

                return_response = self.retry_if_busy(self.send_return_txn)

                return_response_json = return_response.json()
                self.tracker.response = return_response_json
                self.tracker.resolved = datetime.utcnow()

                self.log_api_response(return_response_json)

                if not self.api_response_successful(return_response_json):
                    refund_error = ("Error while running return: "
                                    f"{self.error_message_from_response(return_response_json)}")
                else:
                    self.tracker.success = True
                    refund_txn.receipt_info = self.create_receipt_info(txn.receipt_info.fk_email_model,
                                                                       txn.receipt_info.fk_email_id,
                                                                       return_response_json)

                    self.receipt_manager.items_to_add.append(refund_txn.receipt_info)
                    self.receipt_manager.update_transaction_refund(txn, self.amount)

        if refund_error:
            # Unsuccessful refund, so toss the receipt transaction object
            # Unlike in TransactionRequest, we can't wait until after a successful refund to create it for Reasons:tm:
            self.receipt_manager.items_to_add = [item for item in self.receipt_manager.items_to_add
                                                 if item.id != refund_txn.id]
            return refund_error

    @classmethod
    def intent_id_from_txn_tracker(cls, txn_tracker):
        # Payment terminals need a user-typeable ID so we generate it here to pass to the intent creation functions
        server_digit = "S" if c.DEV_BOX else "P"
        year_digits = c.EVENT_YEAR[2:]
        return f"R{server_digit}{year_digits}{txn_tracker.incr_id}{verhoeff.calculate(str(txn_tracker.incr_id))}"


class ReceiptManager:
    def __init__(self, receipt=None, **params):
        self.receipt = receipt
        self.items_to_add = []
        self.who = ''

    def create_payment_transaction(self, desc='', intent=None, amount=0, txn_total=0, method=c.STRIPE, department=None):
        from uber.models import AdminAccount, ReceiptTransaction

        if intent:
            txn_total = intent.amount
            if not amount:
                amount = txn_total
        else:
            txn_total = txn_total or amount

        if amount <= 0:
            return "There was an issue recording your payment."

        self.items_to_add.append(ReceiptTransaction(receipt_id=self.receipt.id,
                                                    intent_id=intent.id if intent else '',
                                                    method=method,
                                                    department=department or self.receipt.default_department,
                                                    amount=amount,
                                                    txn_total=txn_total or amount,
                                                    receipt_items=self.receipt.open_purchase_items,
                                                    desc=desc,
                                                    who=self.who or AdminAccount.admin_name() or 'non-admin'
                                                    ))
        if not intent:
            for item in self.receipt.open_purchase_items:
                item.closed = datetime.now()
                self.items_to_add.append(item)

    def create_refund_transaction(self, refunded_txn, desc, refund_id, amount, method=c.STRIPE, department=None):
        from uber.models import AdminAccount, ReceiptTransaction

        receipt_txn = ReceiptTransaction(receipt_id=refunded_txn.receipt.id,
                                         refund_id=refund_id,
                                         refunded_txn_id=refunded_txn.id,
                                         method=method,
                                         department=department or refunded_txn.receipt.default_department,
                                         amount=amount * -1,
                                         receipt_items=refunded_txn.receipt.open_credit_items,
                                         desc=desc,
                                         who=self.who or AdminAccount.admin_name() or 'non-admin'
                                         )

        for item in refunded_txn.receipt.open_credit_items:
            self.items_to_add.append(item)
            item.closed = datetime.now()

        self.items_to_add.append(receipt_txn)
        return receipt_txn

    def create_receipt_item(self, receipt, department, category, desc, amount, purchaser_id=None):
        from uber.models import AdminAccount, ReceiptItem

        receipt_item = ReceiptItem(purchaser_id=purchaser_id,
                                   receipt_id=receipt.id,
                                   department=department,
                                   category=category,
                                   desc=desc,
                                   amount=amount,
                                   count=1,
                                   who=self.who or AdminAccount.admin_name() or 'non-admin'
                                   )

        self.items_to_add.append(receipt_item)
        return receipt_item

    def update_transaction_refund(self, txn, refund_amount):
        txn.refunded += refund_amount
        self.items_to_add.append(txn)

    @classmethod
    def get_purchaser_id(cls, receipt=None, model=None):
        from uber.models import Attendee, Group, Session

        if not receipt and not model:
            return None

        with Session() as session:
            model = model or session.get_model_by_receipt(receipt)
            if isinstance(model, Attendee):
                return model.id
            elif isinstance(model, Group):
                if model.leader:
                    return model.leader.id
                else:
                    assigned_badges = [a for a in model.attendees if not a.is_unassigned]
                    return assigned_badges[0].id if assigned_badges else None
            else:
                purchaser = getattr(model, 'attendee', None)
                return purchaser.id if purchaser else None

    @classmethod
    def create_new_receipt(cls, model, who='', create_model=False, purchaser_id=None):
        """
        Iterates through the cost_calculations for this model and returns a list containing
        all non-null cost and credit items.

        This function is for use with new models to grab all their initial costs for creating or previewing a receipt.
        """
        from uber.models import AdminAccount, ModelReceipt, ReceiptItem, Group
        calc_items = uber.receipt_items.receipt_calculation.items
        receipt_items = []
        receipt = ModelReceipt(owner_id=model.id, owner_model=model.__class__.__name__) if create_model else None
        if not purchaser_id:
            purchaser_id = ReceiptManager.get_purchaser_id(model=model)

        def handle_col_name(model, col_name, category):
            # Adds a column's default value to revert_changes
            # and sets the category based on the column, if it has not yet been set.
            default_val = getattr(model.__class__(), col_name, None)
            revert_change[col_name] = default_val
            if getattr(model, 'receipt_changes', None) and category == c.OTHER:
                x, category = model.receipt_changes.get(col_name, (None, c.OTHER))

            return revert_change, category

        for calculation in calc_items[model.__class__.__name__].values():
            item = calculation(model)
            if not item:
                continue
            try:
                desc, cost, col_or_category, count = item
            except ValueError:
                # Unpack list of wrong size (no quantity provided).
                desc, cost, col_or_category = item
                count = 1

            if isinstance(model, Group):
                department = c.DEALER_RECEIPT_ITEM if model.is_dealer else c.REG_RECEIPT_ITEM
            else:
                department = getattr(model, 'department', c.OTHER_RECEIPT_ITEM)
            category = c.OTHER

            revert_change = {}
            if col_or_category and isinstance(col_or_category, tuple):
                for col_name in col_or_category:
                    revert_change, category = handle_col_name(model, col_name, category)
            elif col_or_category and isinstance(col_or_category, int):
                revert_change, category = {}, col_or_category
            elif col_or_category:
                revert_change, category = handle_col_name(model, col_or_category, category)

            if isinstance(cost, Iterable):
                # A list of the same item at different prices, e.g., group badges
                for price in cost:
                    try:
                        price = int(price)
                    except ValueError:
                        log.exception(f"The price for {desc} ({price}) isn't a number!")
                    else:
                        if receipt:
                            receipt_items.append(ReceiptItem(purchaser_id=purchaser_id if price > 0 else None,
                                                             receipt_id=receipt.id,
                                                             department=department,
                                                             category=category,
                                                             desc=desc,
                                                             amount=price,
                                                             count=cost[price],
                                                             revert_change=revert_change,
                                                             ))
                        else:
                            receipt_items.append((desc, price, cost[price]))
            elif receipt:
                receipt_items.append(ReceiptItem(purchaser_id=purchaser_id if cost > 0 else None,
                                                 receipt_id=receipt.id,
                                                 department=department,
                                                 category=category,
                                                 desc=desc,
                                                 amount=cost,
                                                 count=count,
                                                 who=who or AdminAccount.admin_name() or 'non-admin',
                                                 revert_change=revert_change,
                                                 ))
            else:
                receipt_items.append((desc, cost, count))

        return receipt, receipt_items


    @classmethod
    def process_receipt_change(cls, model, col_name, new_model, receipt=None, who='', count=1, revert_change={}):
        from uber.models import AdminAccount, ReceiptItem, Group
        from uber.models.types import Choice

        """
        Finds the cost of a receipt item to add to an existing receipt.
        This uses the cost_changes dictionary defined on each model in receipt_items.py.

        If a ModelReceipt is provided, a new ReceiptItem is created and returned.
        Otherwise, the raw values are returned so attendees can preview their receipt
        changes.
        """
        cost_change_func, category = model.receipt_changes.get(col_name, (None, None))

        if not cost_change_func:
            return

        try:
            cost_desc, cost_change, maybe_category, count = cost_change_func(model, new_model)
        except ValueError:
            # Unpack list of wrong size (no quantity provided).
            cost_desc, cost_change, maybe_category = cost_change_func(model, new_model)
        except TypeError as e:
            log.error(str(e))
            return

        old_val = getattr(model, col_name)
        try:
            old_val = int(old_val)
        except Exception:
            pass

        if isinstance(maybe_category, int):
            category = maybe_category

        if isinstance(model, Group):
            department = c.DEALER_RECEIPT_ITEM if model.is_dealer else c.REG_RECEIPT_ITEM
        else:
            department = getattr(model, 'department', c.OTHER_RECEIPT_ITEM)

        if isinstance(cost_change, Iterable):
            # A list of the same item at different prices, e.g., group badges
            receipt_items = []
            for price in cost_change:
                if receipt:
                    receipt_items.append(ReceiptItem(purchaser_id=ReceiptManager.get_purchaser_id(receipt) if price > 0 else None,
                                                     receipt_id=receipt.id,
                                                     department=department,
                                                     category=category,
                                                     desc=cost_desc,
                                                     amount=price,
                                                     count=cost_change[price],
                                                     revert_change=revert_change,
                                                     ))
                else:
                    receipt_items.append((cost_desc, price, cost_change[price]))
            return receipt_items

        if receipt:
            if not revert_change:
                revert_change = {col_name: old_val} if col_name not in ['promo_code_code', 'badges', 'birthdate'] else {}
            return [ReceiptItem(ReceiptManager.get_purchaser_id(receipt) if cost_change > 0 else None,
                                receipt_id=receipt.id,
                                department=department,
                                category=category,
                                desc=cost_desc,
                                amount=cost_change,
                                count=count,
                                who=who or AdminAccount.admin_name() or 'non-admin',
                                revert_change=revert_change,
                               )]
        else:
            return [(cost_desc, cost_change, count)]

    @classmethod
    def auto_update_receipt(self, model, receipt, params, who=''):
        from uber.models import Attendee, Group, ArtShowApplication, Session
        if not receipt:
            return []

        receipt_items = []
        new_model = model.__class__(**model.to_dict())

        model_overridden_price = getattr(model, 'overridden_price', None)
        overridden_unset = model_overridden_price and (params.get('no_override') or 
                                                       isinstance(model, ArtShowApplication) and params.get('overridden_price', None) == '')
        model_auto_recalc = getattr(model, 'auto_recalc', True) if isinstance(model, Group) else None
        auto_recalc_set = not model_auto_recalc and params.get('auto_recalc', None)

        if overridden_unset or auto_recalc_set:
            # We process this a little differently since the full default cost
            # relies on non-dict-able properties, like groups' # of badges
            old_model = model.__class__(**model.to_dict())

            if overridden_unset:
                revert_change = {'overridden_price': model.overridden_price}

                current_cost = model.overridden_price
                model.overridden_price = None
                new_cost = model.calc_default_cost()
            else:
                revert_change = {'auto_recalc': False, 'cost': model.cost}

                current_cost = model.cost
                model.auto_recalc = True
                new_cost = model.calc_default_cost()

            if new_cost != current_cost:
                items = self.process_receipt_change(old_model,
                                                    'overridden_price' if overridden_unset else 'cost',
                                                    model, receipt, who=who, revert_change=revert_change)
                if items:
                    for receipt_item in items:
                        if receipt_item.amount != 0:
                            receipt_items += [receipt_item]

        if not params.get('no_override') and params.get('overridden_price', None) not in [None, '']:
            new_model.overridden_price = int(params.get('overridden_price') or 0)
            items = self.process_receipt_change(model, 'overridden_price', new_model, receipt, who=who)
            return items if items else []
        elif params.get('no_override'):
            params.pop('overridden_price')

        if not params.get('auto_recalc') and isinstance(model, Group):
            new_model.cost = int(params.get('cost') or 0)
            new_model.auto_recalc = False
            items = self.process_receipt_change(model, 'cost', new_model, receipt, who=who)
            return items if items else []
        else:
            params.pop('cost', None)

        if params.get('power_fee', None) is not None and c.POWER_PRICES.get(int(params.get('power'), 0),
                                                                            None) is None:
            new_model.power_fee = int(params.get('power_fee') or 0)
            new_model.power = int(params.get('power') or 0)
            items = self.process_receipt_change(model, 'power_fee', new_model, receipt, who=who)
            receipt_items += items if items else []
            params.pop('power')
            params.pop('power_fee')

        params = model.auto_update_receipt(params)

        changed_params = []
        for key, val in params.items():
            column = model.__table__.columns.get(key)
            if column is not None:
                coerced_val = model.coerce_column_data(column, val)
                if coerced_val != getattr(model, key, None):
                    changed_params.append(key)
                    setattr(new_model, key, coerced_val)
            if key in ['promo_code_code']:
                if val != getattr(model, key, None):
                    setattr(new_model, 'promo_code', None)
                    with Session() as session:
                        session.add_promo_code_to_attendee(new_model, val)
                        items = self.process_receipt_change(model, key, new_model, receipt, who=who)
                        if items:
                            for receipt_item in items:
                                if receipt_item.amount != 0:
                                    receipt_items += [receipt_item]

        if isinstance(model, Group):
            # "badges" is a property and not a column, so we have to include it explicitly
            maybe_badges_update = params.get('badges', None)
            if maybe_badges_update is not None and maybe_badges_update != model.badges:
                setattr(new_model, 'badges_update', int(maybe_badges_update))
                changed_params.append('badges')

        if isinstance(model, Attendee) and (model.qualifies_for_discounts != new_model.qualifies_for_discounts):
            changed_params.append('birthdate')

        for param in changed_params:
            items = self.process_receipt_change(model, param, new_model, receipt, who=who)
            if items:
                for receipt_item in items:
                    if receipt_item.amount != 0:
                        receipt_items += [receipt_item]

        return receipt_items

    @staticmethod
    def mark_paid_from_stripe_intent(payment_intent):
        if not payment_intent.latest_charge:
            log.error(f"Tried to mark payments with intent ID {payment_intent.id} as paid "
                      "but that intent doesn't have a charge!")
            return []

        if payment_intent.status != "succeeded":
            log.error(f"Tried to mark payments with intent ID {payment_intent.id} as paid "
                      "but the charge on this intent wasn't successful!")
            return []

        return ReceiptManager.mark_paid_from_ids(payment_intent.id, payment_intent.latest_charge)

    @staticmethod
    def mark_paid_from_ids(intent_id, charge_id):
        from uber.models import Attendee, ArtShowApplication, Group, ReceiptTransaction, Session
        from uber.tasks.email import send_email
        from uber.decorators import render

        session = Session().session
        matching_txns = session.query(ReceiptTransaction).filter_by(intent_id=intent_id).filter(
            ReceiptTransaction.charge_id == '').all()

        if not matching_txns:
            log.debug(f"Tried to mark payments with intent ID {intent_id} as paid but we couldn't find any!")
            return []

        for txn in matching_txns:
            if not c.AUTHORIZENET_LOGIN_ID:
                txn.processing_fee = txn.calc_processing_fee()

            txn.charge_id = charge_id
            session.add(txn)
            txn_receipt = txn.receipt

            if txn.cancelled is not None:
                txn.cancelled = None

            for item in txn.receipt_items:
                item.closed = txn.added
                session.add(item)

            session.commit()

            model = session.get_model_by_receipt(txn_receipt)
            if isinstance(model, Attendee) and model.is_paid:
                if model.badge_status == c.PENDING_STATUS:
                    model.badge_status = c.NEW_STATUS
                if model.paid in [c.NOT_PAID, c.PENDING]:
                    model.paid = c.HAS_PAID
            if isinstance(model, Group) and model.is_paid:
                for attendee in model.attendees:
                    if attendee.paid == c.PAID_BY_GROUP and attendee.badge_status == c.NEW_STATUS and \
                                                            not attendee.placeholder and \
                                                                attendee.first_name:
                        attendee.badge_status = c.COMPLETED_STATUS
                        session.add(attendee)
            session.add(model)

            session.commit()
            session.check_receipt_closed(txn_receipt)

            if model and isinstance(model, Group) and model.is_dealer and not txn.receipt.open_purchase_items:
                try:
                    send_email.delay(
                        c.MARKETPLACE_EMAIL,
                        c.MARKETPLACE_NOTIFICATIONS_EMAIL,
                        '{} Payment Completed'.format(c.DEALER_TERM.title()),
                        render('emails/dealers/payment_notification.txt', {'group': model}, encoding=None),
                        model=model.to_dict('id'))
                except Exception:
                    log.error('Unable to send {} payment confirmation email'.format(c.DEALER_TERM), exc_info=True)
            if model and isinstance(model, ArtShowApplication) and not txn.receipt.open_purchase_items:
                try:
                    send_email.delay(
                        c.ART_SHOW_EMAIL,
                        c.ART_SHOW_NOTIFICATIONS_EMAIL,
                        'Art Show Payment Received',
                        render('emails/art_show/payment_notification.txt', {'app': model}, encoding=None),
                        model=model.to_dict('id'))
                except Exception:
                    log.error('Unable to send Art Show payment confirmation email', exc_info=True)

        session.close()
        return matching_txns
