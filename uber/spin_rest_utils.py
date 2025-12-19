import os
import json
import re

from uber.config import c

secrets = json.loads(c.SPIN_REST_SECRETS)
strings = secrets.get("strings", {})
templates = secrets.get("templates", {})

if not strings:
    print("WARN: Starting without spin_rest_utils configured")

def base_request(terminal_id, auth_key):
    return {
            strings.get("terminal_id"): terminal_id,
            strings.get("auth_key"): auth_key,
        }

def sale_request_dict(dollar_amount, payment_type, ref_id, capture_signature):
    sale_request = templates.get("sale_request_dict")
    sale_request[strings.get("dollar_amount")] = dollar_amount
    sale_request[strings.get("payment_type")] = payment_type
    sale_request[strings.get("ref_id")] = ref_id
    sale_request[strings.get("capture_signature")] = capture_signature
    return sale_request

def txn_status_request_dict(payment_type, ref_id):
    return {
            strings.get("payment_type"): payment_type,
            strings.get("ref_id"): ref_id,
            strings.get("print_receipt"): strings.get("false")
        }

def error_message_from_response(response_json):
    status_code = response_json[strings.get("gen_resp")].get(strings.get("sts_code"), "")
    detailed_message = response_json[strings.get("gen_resp")].get(strings.get("det_msg"), response_json[strings.get("gen_resp")].get(strings.get("msg"), 'Unknown error.'))
    return f"{status_code}: {detailed_message}"

def api_response_successful(response_json):
    return response_json[strings.get("gen_resp")].get(strings.get("res"), -1) == strings.get("res_success")

def insecure_entry_type(response_json):
    return response_json[strings.get("cdata")][strings.get("etype")] in secrets.get("lists", {}).get("insecure_entry_types", [])

def approved_amount(response_json):
    return response_json[strings.get("dollar_amounts")][strings.get("total_amount")] if response_json.get(strings.get("dollar_amounts")) else 0

def signature_from_response(response_json):
    return response_json.get(strings.get("sig"), '')

def txn_info_from_response(response_json):
    txn_info = {}
    txn_info['response'] = {}

    txn_info['amount'] = response_json[strings.get("dollar_amounts")][strings.get("total_amount")] if response_json.get(strings.get("dollar_amounts")) else 0
    txn_info['response']['auth_code'] = response_json.get(strings.get("auth_code"), '')
    txn_info['response']['response_code'] = response_json[strings.get("gen_resp")][strings.get("sts_code")] if response_json.get(strings.get("gen_resp")) else ''
    txn_info['response']['message'] = response_json[strings.get("gen_resp")][strings.get("det_msg")] if response_json.get(strings.get("gen_resp")) else ''

    if response_json.get(strings.get("edata"), {}):
        app_name = response_json[strings.get("edata")].get(strings.get("app_name"), '')
        ext_data = response_json[strings.get("ext_data")].get(app_name) if response_json.get(strings.get("ext_data")) else None
    else:
        ext_data = response_json[strings.get("ext_data")]['0'] if response_json.get(strings.get("ext_data")) else None

    if ext_data:
        txn_info['txn_id'] = ext_data.get(strings.get("txn_id"), '')

    return txn_info

def processed_response_info(response_json):
    return response_json.get(strings.get("ref_id"), ''), response_json.get(strings.get("cdata"), {}), response_json.get(strings.get("edata"), {}), \
        response_json[strings.get("rcpt")][strings.get("cust")] if response_json.get(strings.get("rcpt")) else ''

def no_retry_error(response_json):
    error_message = error_message_from_response(response_json)
    return error_message and error_message != strings.get("duplicate_error")

def better_error_message(error_message, response, terminal_id, format_currency):
    status_code_message = re.match(r'^(\d+): (.*)$', error_message)
    if status_code_message:
        status_code = status_code_message[1]
        message = status_code_message[2]
    else:
        status_code = None
        message = error_message

    if message == strings.get("error_busy"):
        return {'message': "The terminal is currently busy. Clear any prompts and try again."}
    if message == strings.get("error_service"):
        return {'message': "The terminal is currently in bypass mode. Press the circle with an arrow curving around it to take it out of bypass mode."}
    if message == strings.get("error_cancel") or str(status_code) == strings.get("sts_cancelled"):
        return {'message': "The transaction was cancelled on the terminal."}
    if message == strings.get("error_partial"):
        return {'message': f"{format_currency(response['Amounts']['TotalAmount'])} has been paid. Retry the payment to charge the remaining balance."}
    if message == strings.get("error_register"):
        return {'error': f'Register {terminal_id} not found.'}

def get_call_url(base_url, type=''):
    if type in secrets.get("lists", {}).get("call_url_types", []):
        return base_url + strings.get(type)