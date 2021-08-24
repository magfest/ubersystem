# Stripe Payments

When an attendees pays through Stripe, they stop interacting with Ubersystem itself and interact directly through Stripe's servers. There are two ways Ubersystem can then finish processing the payment and mark attendees as paid:
1. An automated task running every 30 minutes called **check_missed_stripe_payments()**, located in `uber > tasks > registration.py`. This task polls Stripe's servers via the Stripe API and checks all payment_intent.succeeded events within the last hour to see if they match any attendees whose payments are pending.
2. A webhook integration called **stripe_webhook_handler()**, located in `uber > api.py`, which marks payments as complete as soon as the attendee successfully pays.

## Webhook Integration
### Adding Webhooks to Stripe
In order to make use of the webhook integration, your organization's Stripe account must have a webhook endpoint set up:
1. Follow the instructions at https://stripe.com/docs/webhooks/go-live to add a new webhook endpoint.
    - Set up the webhook for the **payment_intent.succeeded** event and point it to `/api/stripe_webhook_handler` on your server (e.g., `www.example.com/api/stripe_webhook_handler`)
2. Copy the signing secret from the new webhook endpoint into the **stripe_endpoint_secret** value for your server, found in the configuration file (e.g., `development.ini`) under **[secret]**.

### Local Server Testing
Developers can set up Stripe to forward to their localhost server using the Stripe CLI. Follow the instructions at https://stripe.com/docs/webhooks/test to install and run Stripe CLI.

Note that as of this writing, Stripe CLI may stop properly forwarding events when you restart the application. Simply stop and restart the `stripe listen` command to work around this bug.