"""
Integration with uber-vault Lambda service for PCI Vault credit card tokenization.

Flow:
  * Server creates a capture endpoint via Lambda (gets endpoint_id + secret)
  * Server builds an iframe URL pointing to PCI Vault's hosted form
  * Browser loads the iframe; user enters card directly into PCI Vault
  * PCI Vault returns a token via JS callback (postMessage to parent window)
  * Browser sends token back to us
"""

import json
import logging

import boto3

from uber.config import c

log = logging.getLogger(__name__)


def _invoke_lambda(payload):
    """Invoke the uber-vault Lambda function and return the parsed response."""
    client = boto3.client('lambda', region_name=c.VAULT_LAMBDA_REGION)
    response = client.invoke(
        FunctionName=c.VAULT_LAMBDA_FUNCTION_NAME,
        Payload=json.dumps(payload),
    )
    result = json.loads(response['Payload'].read())
    if result.get('statusCode') != 200:
        log.error("Vault Lambda error: %s", result)
        raise RuntimeError(f"Vault Lambda returned status {result.get('statusCode')}: {result.get('body', {}).get('error', 'unknown error')}")
    return result.get('body', {})


def create_capture_session(reference, ttl="PT30M", webhook_metadata=None):
    """Create a temporary capture endpoint on PCI Vault.

    Args:
        reference: PCI Vault reference tag (e.g., "gaylord-national").
                   Used to scope which cards each hotel vendor can retrieve.
        ttl: ISO 8601 duration for endpoint lifetime.

    Returns:
        dict with 'unique_id' and 'secret' keys.
    """
    payload = {
        "method": "create_endpoint",
        "reference": reference,
        "ttl": ttl,
        "return_card_metadata": "true",
    }

    if c.VAULT_WEBHOOK_URL and c.VAULT_WEBHOOK_SECRET:
        webhook = {
            "url": c.VAULT_WEBHOOK_URL,
            "secret": c.VAULT_WEBHOOK_SECRET,
            "max_attempts": 3,
        }
        if webhook_metadata:
            webhook["metadata"] = webhook_metadata
        payload["webhook"] = webhook

    return _invoke_lambda(payload)


def get_capture_iframe_url(endpoint_id, secret, form_id=None, reference=None):
    """Get the iframe URL for a PCI Vault capture form.

    Args:
        endpoint_id: The unique_id from create_capture_session.
        secret: The secret from create_capture_session.
        form_id: Optional custom form ID (defaults to VAULT_CAPTURE_FORM_ID config).
        reference: Optional PCI Vault reference to tag captured cards with.

    Returns:
        URL string to embed in an iframe.
    """
    payload = {
        "method": "get_capture_form",
        "endpoint_id": endpoint_id,
        "secret": secret,
    }
    if form_id or c.VAULT_CAPTURE_FORM_ID:
        payload["form_id"] = form_id or c.VAULT_CAPTURE_FORM_ID
    if reference:
        payload["reference"] = reference

    result = _invoke_lambda(payload)
    return result.get("url", "")


def setup_capture_form(form_id, success_callback_js=None, css_links=None, js_links=None, embedded_js=None):
    """Create or update a hosted capture form on PCI Vault.

    Deletes any existing form with the same ID first, then creates a new one.

    Args:
        form_id: Unique identifier for the form.
        success_callback_js: JS string or base64-encoded JS to run on successful capture.
        css_links: List of CSS URLs to style the form.
        js_links: List of JS URLs to include in the form.
        embedded_js: Base64-encoded JS to include in a script tag in the form.

    Returns:
        dict with form details including 'id'.
    """
    import base64

    # Delete existing form if present so we can recreate it
    try:
        delete_capture_form(form_id)
    except RuntimeError:
        pass  # Form didn't exist, that's fine

    payload = {
        "method": "create_iframe_form",
        "form_type": "pcd",
        "form_id": form_id,
        "css_links": css_links or [],
        "js_links": js_links or [],
        "strip_spaces": True,
    }
    if success_callback_js:
        if isinstance(success_callback_js, str):
            success_callback_js = base64.b64encode(success_callback_js.encode()).decode()
        payload["success_callback"] = success_callback_js
    if embedded_js:
        payload["embedded_js"] = embedded_js

    return _invoke_lambda(payload)


def delete_capture_form(form_id):
    """Delete a hosted capture form."""
    return _invoke_lambda({
        "method": "delete_iframe_form",
        "form_id": form_id,
    })


def delete_capture_endpoint(endpoint_id):
    """Delete a capture endpoint (cleanup)."""
    return _invoke_lambda({
        "method": "delete_endpoint",
        "endpoint_id": endpoint_id,
    })


def get_usage(month=None):
    """Get usage statistics from PCI Vault.

    Args:
        month: Optional month string (e.g., "2026-04"). Defaults to current month.

    Returns:
        dict with usage data from PCI Vault.
    """
    payload = {"method": "get_usage"}
    if month:
        payload["month"] = month
    return _invoke_lambda(payload)


def get_billing():
    """Get month-to-date billing information from PCI Vault.

    Returns:
        dict with billing data from PCI Vault.
    """
    return _invoke_lambda({"method": "get_billing"})
