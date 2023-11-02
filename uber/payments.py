import pytz
from typing import Iterable
from collections import OrderedDict
from datetime import datetime, timedelta
from dateutil.parser import parse
from uuid import uuid4

import cherrypy
import stripe
from authorizenet import apicontractsv1, apicontrollers
from pockets import cached_property, classproperty, is_listy, listify
from pockets.autolog import log

import uber
from uber.config import c
from uber.custom_tags import format_currency, email_only
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
    def __init__(self, amount, description, receipt_email='', customer_id=''):
        self.id = str(uuid4()).replace('-', '')[:20]
        self.amount = amount
        self.description = description
        self.receipt_email = receipt_email
        self.customer_id = customer_id
        self.charges = None

        # And now for the serializable info!
        dict.__init__(self, id=self.id, amount=amount, description=description, receipt_email=receipt_email,
                      customer_id = customer_id, charges=self.charges)


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
        return ['paid_preregs', 'unpaid_preregs', 'pending_preregs', 'pending_dealers', 'payment_intent_id', 'universal_promo_codes']

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
        email = self.models[0].email if self.models and self.models[0].email else ''
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
                items_group = ("{} plus {} badges ({})".format(getattr(model, 'full_name', None), int(model.badges) - 1, model.name), [])
                x, receipt_items = ReceiptManager.create_new_receipt(PromoCodeGroup())
            else:
                group_name = getattr(model, 'name', None)
                items_group = (group_name or getattr(model, 'full_name', None), [])
            
            x, receipt_items = ReceiptManager.create_new_receipt(model)
            items_group[1].extend(receipt_items)
            
            items_preview.append(items_group)

        return items_preview
    

class TransactionRequest:
    def __init__(self, receipt=None, receipt_email='', description='', amount=0, customer_id=None, create_receipt_item=False):
        self.amount = int(amount)
        self.receipt_email = receipt_email[0] if isinstance(receipt_email, list) else receipt_email
        self.description = description
        self.customer_id = customer_id
        self.refund_str = "refunded" # Set to "voided" when applicable to better inform admins
        self.intent, self.response, self.receipt_manager = None, None, None
        self.tracking_id = str(uuid4())

        log.debug(f"Transaction {self.tracking_id} started with {amount} amount, {receipt_email} receipt email, {description} description, and {customer_id} customer ID.")

        if receipt:
            log.debug(f"Transaction {self.tracking_id} initialized with receipt id {receipt.id}, which has {receipt.current_amount_owed} balance due.")
            self.receipt_manager = ReceiptManager(receipt)
            if not self.amount:
                self.amount = receipt.current_amount_owed
            if create_receipt_item:
                self.receipt_manager.create_custom_receipt_item(receipt, self.description, self.amount)

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
        return self.amount // 100
        
    def get_receipt_items_to_add(self):
        if not self.receipt_manager:
            return
        items_to_add = self.receipt_manager.items_to_add
        self.receipt_manager.items_to_add = []
        return items_to_add

    def create_stripe_intent(self):
        """
        Creates a Stripe Intent, which is what Stripe uses to process payments.
        After calling this, call create_payment_transaction with the Stripe Intent object
        and the receipt to add the new transaction to the receipt.
        """

        if not self.amount or self.amount <= 0:
            log.error('Was asked for a Stripe Intent but the currently owed amount is invalid: {}'.format(self.amount))
            return "There was an error calculating the amount. Please refresh the page or contact the system admin."

        if self.amount > 999999:
            return "We cannot charge {}. Please make sure your total is below $9,999.".format(format_currency(self.amount / 100))
        try:
            self.intent = self.stripe_or_authnet_intent()
        except Exception as e:
            error_txt = 'Got an error while creating a Stripe intent for transaction {self.tracking_id}'
            report_critical_exception(msg=error_txt, subject='ERROR: MAGFest Stripe invalid request error')
            return 'An unexpected problem occurred while setting up payment: ' + str(e)
        
    def stripe_or_authnet_intent(self):
        if not self.customer_id:
            self.get_or_create_customer()

        if c.AUTHORIZENET_LOGIN_ID:
            return MockStripeIntent(
                amount=self.amount,
                description=self.description,
                receipt_email=self.receipt_email,
                customer_id=self.customer_id
            )
        else:
            log.debug('Transaction {self.tracking_id}: creating Stripe Intent to charge {} cents for {}',
                      self.amount, self.description)

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
                return "This transaction cannot be refunded because of an invalid status: {}.".format(self.response.transactionStatus)
            else:
                if parse(str(self.response.submitTimeUTC)).replace(tzinfo=pytz.UTC) < datetime.now(pytz.UTC) - timedelta(days=180):
                    return "This transaction is more than 180 days old and cannot be refunded automatically."

                if self.response.settleAmount * 100 < self.amount:
                    return "This transaction was only for {} so it cannot be refunded {}.".format(
                        format_currency(self.response.settleAmount),
                        format_currency(self.amount / 100))
                cc_num = str(self.response.payment.creditCard.cardNumber)[-4:]
                zip = str(self.response.billTo.zip)
                error = self.send_authorizenet_txn(txn_type=c.REFUND, amount=amount, cc_num=cc_num, zip=zip, txn_id=txn.charge_id)
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
            
    def refund_or_cancel(self, txn):
        if not self.amount:
            return "You must enter an amount to refund."

        error = self._pre_process_refund(txn)
        if not error:
            error = self._process_refund(txn)

        if error:
            return error
        
    def refund_or_skip(self, txn):
        if not self.amount:
            return "You must enter an amount to refund."

        error = self._pre_process_refund(txn)
        if error:
            return
        
        error = self._process_refund(txn)

        if error:
            return error
        
    def _pre_process_refund(self, txn):
        """
        Performs error checks and updates transactions to prepare them for _process_refund.
        This is split out from _process_refund because sometimes we want to skip transactions
        that can't be refunded and other times we want to cancel if we find an issue.
        """
        from uber.custom_tags import format_currency

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
            return "There is not enough left on this transaction to refund {}.".format(format_currency(refund_amount / 100))

    def _process_refund(self, txn):
        """
        Attempts to refund a given Stripe transaction and add/update the relevant transactions on the receipt.
        Returns an error message or sets the object's response property if the refund was successful.
        """
        if not self.receipt_manager:
            log.error("ERROR: _process_refund was called using an object without a receipt; we can't save anything that way!")
            return "There was an issue recording your refund. Please contact the developer."

        refund_amount = self.amount or txn.amount_left

        log.debug('REFUND: attempting to refund card transaction with ID {} {} cents for {}',
                    txn.stripe_id, refund_amount, txn.desc)

        message = self.stripe_or_authnet_refund(txn, int(refund_amount))
        if message:
            return message
        
        self.receipt_manager.create_refund_transaction(txn.receipt,
                                                       "Automatic refund of transaction " + txn.stripe_id,
                                                       str(self.response_id),
                                                       self.amount)
        self.receipt_manager.update_transaction_refund(txn, self.amount)

    def process_payment(self, payment_method=c.STRIPE):
        """
        Creates the stripe intent and receipt transaction for a given payment processor object.
        Most methods should call this instead of calling create_stripe_intent and 
        create_payment_transaction directly.
        """
        if not self.receipt_manager:
            log.error("ERROR: process_payment was called using an object without a receipt; we can't save anything that way!")
            return "There was an issue recording your payment. Please contact the developer."
        
        message = self.create_stripe_intent()
        if not message:
            message = self.receipt_manager.create_payment_transaction(self.description, self.intent, method=payment_method)
        
        if message:
            return message
        
    def get_or_create_customer(self, customer_id=''):
        if not self.receipt_email:
            return
        
        if c.AUTHORIZENET_LOGIN_ID:
            log.debug(f"Transaction {self.tracking_id} getting or creating a customer with ID {customer_id} and email {self.receipt_email}")
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
                if response.messages.resultCode == "Ok" and hasattr(response, 'profile') == True:
                    self.customer_id = str(response.profile.customerProfileId)
                    log.debug(f"Transaction {self.tracking_id} retrieved customer {self.customer_id}")
                    if hasattr(response.profile, 'paymentProfiles') == True:
                        for paymentProfile in response.profile.paymentProfiles:
                            log.debug(f"Transaction {self.tracking_id} deleting payment profile ID {str(paymentProfile.customerPaymentProfileId)} from customer {self.customer_id}")
                            self.delete_authorizenet_payment_profile(str(paymentProfile.customerPaymentProfileId))
                elif response.messages.message.code == 'E00040':
                    log.debug(f"Transaction {self.tracking_id} did not find customer, creating a new one...")
                    createCustomerRequest = apicontractsv1.createCustomerProfileRequest()
                    createCustomerRequest.merchantAuthentication = self.merchant_auth
                    createCustomerRequest.profile = apicontractsv1.customerProfileType(email=self.receipt_email)

                    createCustomerRequestController = apicontrollers.createCustomerProfileController(createCustomerRequest)
                    createCustomerRequestController.setenvironment(c.AUTHORIZENET_ENDPOINT)
                    createCustomerRequestController.execute()

                    response = createCustomerRequestController.getresponse()

                    if response and (response.messages.resultCode=="Ok"):
                        self.customer_id = str(response.customerProfileId)
                    elif not response:
                        log.error(f"Transaction {self.tracking_id} failed to create customer profile. No response received.")
                    else:
                        log.error(f"Transaction {self.tracking_id} failed to create customer profile. {str(response.messages.message[0]['code'].text)}: {str(response.messages.message[0]['text'].text)}")
                else:
                    log.error(f"Transaction {self.tracking_id} failed to retrieve customer profile. {str(response.messages.message[0]['code'].text)}: {str(response.messages.message[0]['text'].text)}")
            else:
                log.error(f"Failed to retrieve customer profile for AuthNet: no response received.")
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

        createCustomerPaymentController = apicontrollers.createCustomerPaymentProfileController(createCustomerPaymentRequest)
        createCustomerPaymentController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        createCustomerPaymentController.execute()

        response = createCustomerPaymentController.getresponse()
        if (response.messages.resultCode=="Ok"):
            profileToCharge = apicontractsv1.customerProfilePaymentType()
            profileToCharge.customerProfileId = self.customer_id
            profileToCharge.paymentProfile = apicontractsv1.paymentProfile()
            profileToCharge.paymentProfile.paymentProfileId = str(response.customerPaymentProfileId)

            log.debug(f"Transaction {self.tracking_id} successfully created a payment profile (ID {str(response.customerPaymentProfileId)}) for customer {self.customer_id}")

            return profileToCharge
        else:
            log.error(f"Transaction {self.tracking_id} failed to create customer payment profile: {response.messages.message[0]['text'].text}")
    
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

        if (response.messages.resultCode!="Ok"):
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
                log.error(f"Transaction {self.tracking_id} requested {txn_id} from AuthNet but received an error: \
                          {response.messages.message[0]['code'].text}: {response.messages.message[0]['text'].text}")
                return 'Failed to get transaction details from AuthNet. {}: {}'.format(response.messages.message[0]['code'].text,response.messages.message[0]['text'].text)

        return response
    
    def send_authorizenet_txn(self, txn_type=c.AUTHCAPTURE, **params):
        from decimal import Decimal

        payment_profile = None
        order = None

        params_str = [f"{name}: {params[name]}" for name in params]
        log.debug(f"Transaction {self.tracking_id} building an AuthNet transaction request, request type '{c.AUTHNET_TXN_TYPES[txn_type]}'. Params: {params_str}")
        
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
                        return f"Could not complete payment. Please contact us at {email_only(c.REGDESK_EMAIL)}"

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
            transaction.amount = Decimal(int(self.amount)) / Decimal(100)

        transactionRequest = apicontractsv1.createTransactionRequest()
        transactionRequest.merchantAuthentication = self.merchant_auth
        transactionRequest.transactionRequest = transaction
        
        transactionController = apicontrollers.createTransactionController(transactionRequest)
        transactionController.setenvironment(c.AUTHORIZENET_ENDPOINT)
        transactionController.execute()

        response = transactionController.getresponse()

        if response is not None:
            if response.messages.resultCode == "Ok":
                if hasattr(response.transactionResponse, 'messages') == True:
                    self.response = response.transactionResponse
                    auth_txn_id = str(self.response.transId)

                    log.debug(f"Transaction {self.tracking_id} request successful. Transaction ID: {auth_txn_id}")
                    
                    if txn_type in [c.AUTHCAPTURE, c.CAPTURE]:
                        ReceiptManager.mark_paid_from_ids(params.get('intent_id'), auth_txn_id)
                else:
                    error_code = str(response.transactionResponse.errors.error[0].errorCode)
                    error_msg = str(response.transactionResponse.errors.error[0].errorText)
                    log.debug(f"Transaction {self.tracking_id} request did not receive a transaction response! {error_code}: {error_msg}")

                    return str(response.transactionResponse.errors.error[0].errorText)
            else:
                if hasattr(response, 'transactionResponse') == True and hasattr(response.transactionResponse, 'errors') == True:
                    error_code = response.transactionResponse.errors.error[0].errorCode
                    error_msg = response.transactionResponse.errors.error[0].errorText
                else:
                    error_code = response.messages.message[0]['code'].text
                    error_msg = response.messages.message[0]['text'].text
                    
                log.debug(f"Transaction {self.tracking_id} request failed! {error_code}: {error_msg}")
                    
                return str(error_msg)
        else:
            log.error(f"Transaction {self.tracking_id} request to AuthNet failed: no response received.")
        

class ReceiptManager:
    def __init__(self, receipt=None, **params):
        self.receipt = receipt
        self.items_to_add = []

    def create_payment_transaction(self, desc='', intent=None, amount=0, txn_total=0, method=c.STRIPE):
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
                                                    intent_id=intent.id,
                                                    amount=amount,
                                                    txn_total=txn_total or amount,
                                                    receipt_items=self.receipt.open_receipt_items,
                                                    desc=desc,
                                                    method=method,
                                                    who=AdminAccount.admin_name() or 'non-admin'
                                                    ))

    def create_refund_transaction(self, receipt, desc, refund_id, amount):
        from uber.models import AdminAccount, ReceiptTransaction
        self.items_to_add.append(ReceiptTransaction(receipt_id=receipt.id,
                                                    refund_id=refund_id,
                                                    amount=amount * -1,
                                                    desc=desc,
                                                    who=AdminAccount.admin_name() or 'non-admin'
                                                    ))

    def create_receipt_item(self, receipt, desc, amount):
        from uber.models import AdminAccount, ReceiptItem

        self.items_to_add.append(ReceiptItem(receipt_id=receipt.id,
                                    desc=desc,
                                    amount=amount,
                                    count=1,
                                    who=AdminAccount.admin_name() or 'non-admin'
                                ))

    def update_transaction_refund(self, txn, refund_amount):
        txn.refunded += refund_amount
        self.items_to_add.append(txn)

    def create_custom_receipt_item(self, receipt, desc, amount):
        from uber.models import AdminAccount, ReceiptItem

        self.items_to_add.append(ReceiptItem(receipt_id=receipt.id,
                                    desc=desc,
                                    amount=amount,
                                    count=1,
                                    who=AdminAccount.admin_name() or 'non-admin'
                                ))

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
                        desc, cost, col_name, count = item
                    except ValueError:
                        # Unpack list of wrong size (no quantity provided).
                        desc, cost, col_name = item
                        count = 1

                    default_val = getattr(model.__class__(), col_name, None) if col_name else None
                    if isinstance(cost, Iterable):
                        # A list of the same item at different prices, e.g., group badges
                        for price in cost:
                            if receipt:
                                receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                                desc=desc,
                                                                amount=price,
                                                                count=cost[price],
                                                                who=AdminAccount.admin_name() or 'non-admin',
                                                                revert_change={col_name: default_val} if col_name else {}
                                                                ))
                            else:
                                receipt_items.append((desc, price, cost[price]))
                    elif receipt:
                        receipt_items.append(ReceiptItem(receipt_id=receipt.id,
                                                         desc=desc,
                                                         amount=cost,
                                                         count=count,
                                                         who=AdminAccount.admin_name() or 'non-admin',
                                                         revert_change={col_name: default_val} if col_name else {}
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
        if not credit_change_tuple:
            return
        
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
        from uber.models import AdminAccount, ReceiptItem
        from uber.models.types import Choice

        """
        Finds the cost of a receipt item to add to an existing receipt.
        This uses the cost_changes dictionary defined on each model in receipt_items.py,
        calling it with the extra keyword arguments provided. If no function is specified,
        we use calc_simple_cost_change instead.
        
        If a ModelReceipt is provided, a new ReceiptItem is created and returned.
        Otherwise, the raw values are returned so attendees can preview their receipt 
        changes.
        """
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

    @classmethod
    def auto_update_receipt(self, model, receipt, params):
        from uber.models import Attendee, Group, ReceiptItem, AdminAccount
        if not receipt:
            return []

        receipt_items = []

        model_overridden_price = getattr(model, 'overridden_price', None)
        overridden_unset = model_overridden_price and not params.get('overridden_price')
        model_auto_recalc = getattr(model, 'auto_recalc', True) if isinstance(model, Group) else None
        auto_recalc_unset = not model_auto_recalc and params.get('auto_recalc', None)

        if overridden_unset or auto_recalc_unset:
            # Note: we can't use preview models here because the full default cost
            # relies on non-dict-able properties, like groups' # of badges
            if overridden_unset:
                current_cost = model.overridden_price
                model.overridden_price = None
                new_cost = model.default_cost

                revert_change = {'overridden_price': model.overridden_price}
            else:
                current_cost = model.cost
                model.auto_recalc = True
                new_cost = model.default_cost

                revert_change = {'auto_recalc': True, 'cost': model.cost}
            
            if new_cost != current_cost:
                cost_change = new_cost - current_cost
                receipt_items += [ReceiptItem(receipt_id=receipt.id,
                                    desc=f"Reverting to default price from custom price of ${current_cost}",
                                    amount=cost_change * 100,
                                    count=1,
                                    who=AdminAccount.admin_name() or 'non-admin',
                                    revert_change=revert_change,
                                )]

        if not params.get('no_override') and params.get('overridden_price'):
            receipt_item = self.add_receipt_item_from_param(model, receipt, 'overridden_price', params)
            return [receipt_item] if receipt_item else []

        if not params.get('auto_recalc') and isinstance(model, Group):
            receipt_item = self.add_receipt_item_from_param(model, receipt, 'cost', params)
            return [receipt_item] if receipt_item else []
        else:
            params.pop('cost', None)
        
        if params.get('power_fee', None) != None and c.POWER_PRICES.get(int(params.get('power'), 0), None) == None:
            receipt_item = self.add_receipt_item_from_param(model, receipt, 'power_fee', params)
            receipt_items += [receipt_item] if receipt_item else []
            params.pop('power')
            params.pop('power_fee')

        changed_params = {}
        for key, val in params.items():
            column = model.__table__.columns.get(key)
            if column is not None:
                coerced_val = model.coerce_column_data(column, val)
                if coerced_val != getattr(model, key, None):
                    changed_params[key] = coerced_val
        
        if isinstance(model, Group):
            # "badges" is a property and not a column, so we have to include it explicitly
            maybe_badges_update = params.get('badges', None)
            if maybe_badges_update != None and maybe_badges_update != model.badges:
                changed_params['badges'] = maybe_badges_update
        
        cost_changes = getattr(model.__class__, 'cost_changes', [])
        credit_changes = getattr(model.__class__, 'credit_changes', [])
        for param in changed_params:
            if param in credit_changes:
                receipt_item = self.add_receipt_item_from_param(model, receipt, param, changed_params, 'process_receipt_credit_change')
                receipt_items += [receipt_item] if receipt_item else []
            elif param in cost_changes:
                receipt_item = self.add_receipt_item_from_param(model, receipt, param, changed_params)
                receipt_items += [receipt_item] if receipt_item else []
        
        return receipt_items

    @classmethod
    def add_receipt_item_from_param(self, model, receipt, param_name, params, func_name='process_receipt_upgrade_item'):
        charge_func = getattr(ReceiptManager, func_name)
        try:
            receipt_item = charge_func(model, param_name, receipt=receipt, new_val=params[param_name])
            if receipt_item.amount != 0:
                return receipt_item
        except Exception as e:
            log.error(str(e))

    @staticmethod
    def mark_paid_from_stripe_intent(payment_intent):
        if not payment_intent.charges.data:
            log.error(f"Tried to mark payments with intent ID {payment_intent.id} as paid but that intent doesn't have a charge!")
            return []

        if payment_intent.status != "succeeded":
            log.error(f"Tried to mark payments with intent ID {payment_intent.id} as paid but the charge on this intent wasn't successful!")
            return []
        
        return ReceiptManager.mark_paid_from_ids(payment_intent.id, payment_intent.charges.data[0].id)
        
    @staticmethod
    def mark_paid_from_ids(intent_id, charge_id):
        from uber.models import Attendee, ArtShowApplication, MarketplaceApplication, Group, ReceiptTransaction, Session
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

            if txn.cancelled != None:
                txn.cancelled == None

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
                        c.MARKETPLACE_NOTIFICATIONS_EMAIL,
                        '{} Payment Completed'.format(c.DEALER_TERM.title()),
                        render('emails/dealers/payment_notification.txt', {'group': model}, encoding=None),
                        model=model.to_dict('id'))
                except Exception:
                    log.error('Unable to send {} payment confirmation email'.format(c.DEALER_TERM), exc_info=True)
            if model and isinstance(model, ArtShowApplication) and not txn.receipt.open_receipt_items:
                try:
                    send_email.delay(
                        c.ART_SHOW_EMAIL,
                        c.ART_SHOW_NOTIFICATIONS_EMAIL,
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
