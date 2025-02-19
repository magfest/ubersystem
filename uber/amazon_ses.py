import http.client
import urllib.request, urllib.parse, urllib.error
import hashlib
import hmac
import logging
import base64
import boto3
import os

from botocore.exceptions import ClientError
from datetime import datetime
from pockets.autolog import log
from xml.etree.ElementTree import XML

from uber.config import c


class AmazonSES:
    def __init__(self, region="us-east-1"):
        os.environ["AWS_ACCESS_KEY_ID"] = c.AWS_ACCESS_KEY
        os.environ["AWS_SECRET_ACCESS_KEY"] = c.AWS_SECRET_KEY

        self._client = boto3.client('ses', region_name=region)

    def sendEmail(self, source, toAddresses, message, replyToAddresses=None, returnPath=None, ccAddresses=None, bccAddresses=None):
        params = { 'Source': source }
        destinations = {}
        for objName, addresses in zip(["ToAddresses", "CcAddresses", "BccAddresses", "replyToAddresses"],
                                      [toAddresses, ccAddresses, bccAddresses, replyToAddresses]):
            if addresses:
                if not isinstance(addresses, str) and getattr(addresses, '__iter__', False):
                    destinations[objName] = [a for a in addresses]
                else:
                    destinations[objName] = addresses.split(', ')
        if not returnPath:
            returnPath = source
        message_dict = {}
        if 'bodyText' in message:
            message_dict['Text'] = {'Charset': message['charset'] or 'UTF-8', 'Data': message['bodyText']}
        if 'bodyHtml' in message:
            message_dict['Html'] = {'Charset': message['charset'] or 'UTF-8', 'Data': message['bodyHtml']}

        try:
            response = self._client.send_email(
                Source=source,
                Destination=destinations,
                Message={
                    'Body': message_dict,
                    'Subject': {
                        'Charset': message['charset'],
                        'Data': message['subject'],
                    },
                },
                ReplyToAddresses=replyToAddresses,
                ReturnPath=returnPath or source,
            )
            log.info("Sent email. Response: " + str(response))
        except ClientError as e:
            return e.response['Error']['Message']
        except Exception as e:
            return e

email_sender = AmazonSES(c.AWS_REGION_EMAIL)
