#!/usr/bin/env python3

# GmailTools
# Copyright (C) 2020, Oren Laadan
#
# All rights reserved.
#
# This source code is licensed under the 3-clause BSD license found in the
# LICENSE file in the root directory of this source tree.
#

import argparse
import json
import logging
import os
import re
import sys
import time

# date/time parsing (--since <date>)
import datetime

# gmail api access
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

########################################################################
# constants

# If modifying these scopes, delete the file oauth2token.json
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

LABELS_SYSTEM = [
        'CHAT',
        'SENT',
        'INBOX',
        'IMPORTANT',
        'TRASH',
        'DRAFT',
        'SPAM',
        'CATEGORY_FORUMS',
        'CATEGORY_UPDATES',
        'CATEGORY_PERSONAL',
        'CATEGORY_PROMOTIONS',
        'CATEGORY_SOCIAL',
        'STARRED',
        'UNREAD',
        ]

LABELS_USER = 'Label_'

# file to hold base credentials
CREDS_FILE = 'credentials.json'

# file to save existing token
TOKEN_FILE = 'oauth2token.json'

# gmail api rate limits (calls per second)
# https://developers.google.com/gmail/api/reference/quota (as of Nov 16, 2020)
RATE_LABELS_LIST = 1
RATE_THREADS_LIST = 10
RATE_THREADS_GET = 10
RATE_THREADS_MODIFY = 10
RATE_MESSAGES_BATCH_MODIFY = 50
RATE_LIMIT = 250

########################################################################
# _statusbar

class _Context:
    """Holds last execution progress context.
    Intended to be printed to provide context if an error occurs.
    """

    _status = 'n/a'

    def get():
        return _Context._status

    def set(str):
        _Context._status = str

########################################################################
# gmail api helpers

class RateLimit(object):
    """Simple rate limiter
    Ensure that an operation will not be executed more at more than a given
    rate. Useful to make sure a client complies with a server's api quotas.

    RateLimiter is initialized with a 'rate'. It implements a "token bucket"
    of initial size 'rate', refilled at 'rate' tokens per second. A caller
    uses tokens from the bucket as available, or blocks until sufficiently
    refills.

    Typical usage:
        ...
        limiter = RateLimiter(rate)   # 'rate' is max rate per second
        ...
        limiter.wait(units)           # use 'units' tokens (wait if needed)
        do_api_call(...)
        ...
    """

    def __init__(self, rate):
        self.rate = rate
        self.units = float(rate)
        self.time = datetime.datetime.now()

    def _update(self):
        now = datetime.datetime.now()
        delta = now - self.time
        units = (delta.microseconds/1000000 + delta.seconds) * self.rate
        self.units = min(self.units + units, self.rate)
        self.time = now

    def wait(self, units=1):
        """try to use tokens, wait for bucket to refill if needed
        Args: units: number of tokens requested
        """

        if units > self.rate:
            raise Exception("ratelimit: request too big (req: {}, max {})".
                format(units, self.rate))
        self._update()
        while units > self.units:
            delta = (units - self.units) / self.rate
            time.sleep(delta)
            self._update()
        self.units = self.units - units

########################################################################
# gmail api helpers

def get_gmail_service(creds_path, token_path):
    """Prepares and returns the credentials to access the API.
    Returns: the credentials object.
    """

    _Context.set('Auth: connecting to gmail api service')

    # The file TOKEN_FILE stores the user's access and refresh tokens, created
    # automatically when the authorization flow completes for the first time.
    if os.path.exists(token_path):
        with open(token_path, 'r') as token:
            logging.info('Auth: Loading existing token from file')
            creds = Credentials.from_authorized_user_info(json.load(token))
    else:
        creds = None

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logging.info('Auth: Refreshing expired existing token')
            creds.refresh(Request())
        else:
            logging.info('Auth: Requesting new token')
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_path, 'w') as token:
            data = json.loads(creds.to_json())
            json.dump(data, token, indent=2)

    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    return service

def get_labels(service):
    """Gets the full list of labels from the API.
    Args: service: service handler of the API.
    Returns: list of label objects.
    """

    _Context.set('Label: retrieving list of labels')

    limiter.wait(RATE_LABELS_LIST)
    request = service.users().labels().list(userId='me')
    response = request.execute()

    labels = response.get('labels', [])
    return labels

def is_user_label(label):
    """Tests whether the label is system (gmail) or user defined
    Args: label: label to check.
    Returns: True/False.
    """

    id = label['id']
    if id.startswith(LABELS_USER):
        return True

    if id not in LABELS_SYSTEM:
        logging.warn('unrecognized label <{}, {}>, consider system', label['name'], id)

    return False

def labels_name(labels):
    if type(labels) is list:
        return ','.join([ l['name'] for l in labels ])
    else:
        return labels['name']

def labels_ids(labels):
    if type(labels) is list:
        return [ l['id'] for l in labels ]
    else:
        return [ l['id'] ]

def get_threads(service, labels=None, query=None):
    """Generator for the list of threads with this label.
    Args: service: gmail api service object.
          label: label that the threads should have.
          query: filter query for gmail api
    Returns: thread objects.
    """

    _Context.set('Label {}: retrieving list of threads'.
            format(labels_name(labels)))

    limiter.wait(RATE_THREADS_LIST)
    request = service.users().threads().list(
            userId='me', labelIds=labels_ids(labels), q=query)
    response = request.execute()

    threads = response.get('threads', [])
    for thread in threads:
        yield thread

    while response.get('nextPageToken'):
        limiter.wait(RATE_THREADS_LIST)
        request = service.users().threads().list_next(
                previous_request=request, previous_response=response)
        response = request.execute()
        threads = response.get('threads', [])
        for thread in threads:
            yield thread

    return

def thread_add_label(service, thread, label):
    """Add a label to a thread.
    Args: service: gmail api service object.
          thread: affected thread.
          label: label to add.
    Returns: N/A
    """

    _Context.set('Thread {}: adding label {}'.format(thread['id'], label['name']))

    tid = thread['id']
    body = { "addLabelIds": [label['id']] }

    limiter.wait(RATE_THREADS_MODIFY)
    request = service.users().threads().modify(userId='me', id=tid, body=body)
    response = request.execute()

def thread_get_messages(service, thread):
    """Get the list of messages in a given thread.
    Args: service: gmail api service object.
          thread: thread from which to get the messages.
    Returns: list of messages obects (minimal format: only id and label).
    """

    _Context.set('Thread {}: retrieving list of messages'.format(thread['id']))

    limiter.wait(RATE_THREADS_GET)
    request = service.users().threads().get(userId='me', format='minimal', id=thread['id'])
    response = request.execute()

    messages = response.get('messages', [])
    return messages

def message_has_label(message, label):
    """Tests whether a message has a label
    Args: message: message to consider.
          label: label to check.
    Returns: True/False.
    """

    return label['id'] in message.get('labelIds', [])

def messages_add_label(service, messages, label):
    """Add a label to a list of message.
    Args: service: gmail api service object.
          messages: list of affected messages.
          label: label to add.
    Returns: N/A
    """

    _Context.set('Thread {}: adding label {} (messages: {})'.format(
            messages[0]['id'], label['name'], [ msg['id'] for msg in messages ]))

    body = {
        'ids': [msg['id'] for msg in messages],
        'addLabelIds': [label['id']],
        }

    response = service.users().messages().batchModify(userId='me', body=body).execute()

########################################################################
# subcommands

def relabel(args):
    """Relabel all unlabeled messages in a labeled threads.
    Args: creds_path: path to credentials file (json)
          token_path: path to saved token file (json)
    Returns: N/A
    """

    service = get_gmail_service(creds_path=args.credsfile, token_path=args.tokenfile)

    #
    # relabeling works as follow:
    #
    # 1) get the list of all user labels (ignore system labels)
    # 2) for each such label:
    # 3)   get the list of all threads with that label
    # 3)   for each such thread:
    # 4)     get list of messages not labeled as such
    # 5)     label the unlabeled messages or the entire thread
    #
    # in step (5), if there are more than UNLABELED_MANY unlabeled
    # messages and they are at least half the thread size, then we
    # relabel the entire thread; otherwise re-label the individual
    # messages (as a batch).
    #

    labels = get_labels(service)
    labels_user = [l for l in labels if is_user_label(l)]
    logging.info('Labels: received total of {} user labels'.
            format(len(labels_user)))

    if args.label is not None:
        labels_asked = ','.join(args.label).split(',')
        labels_user = [l for l in labels_user if l['name'] in labels_asked]

    query = None
    filters = []
    if args.since is not None:
        filters.append('after:{}'.format(args.since))
    if args.until is not None:
        filters.append('before:{}'.format(args.until))
    if len(filters) > 0:
        query = ' '.join(filters)

    for label in labels_user:
        logging.debug('  {:32} ({})'.format(label['name'], label['id']))

    for label in labels_user:
        threads_label = list(get_threads(service, labels=[label], query=query))
        logging.info('label: {}, total threads {}'.
                format(label['name'], len(threads_label)))

        for thread in threads_label:
            messages = thread_get_messages(service, thread)
            no_label = list(filter(lambda m: not message_has_label(m, label), messages))
            logging.info('|- thread: {}, un/labeled messages {:>2}/{:<2}'.
                    format(thread['id'], len(no_label), len(messages)))

            if len(no_label) == 0:
                continue

            # Can use either 'threads.modify' or 'messages.batchmodify' api calls;
            # Choose the one that is cheaper in terms of api quota usage.

            if RATE_THREADS_MODIFY < RATE_MESSAGES_BATCH_MODIFY:
                if args.dryrun:
                    logging.debug(' |- thread {}: re-label {}'.
                            format(thread['id'], label['name']))
                    continue
                thread_add_label(service, thread, label)
            else:
                if args.dryrun:
                    logging.debug(' |- thread {}: messages {}'.
                            format(thread['id'], no_label))
                    continue
                messages_add_label(service, no_label, label)

    logging.info('Done')

########################################################################
# cli parsing

def parse_arg_date(arg):
    """parse date argument in the following format:
         'YYYY-MM-DAY',
         'today', 'yesterday',
         'NN day|day|days ago',
         'NN wk|wks|week|weeks|w ago'
         'NN yr|yrs|year|years|y ago'
    Args: date argument.
    Returns: date in 'YYYY-MM-DD' format.
    """

    today = datetime.date.today()
    splitted = arg.split()

    if len(splitted) == 1:
        if splitted[0].lower() == 'today':
            return str(today.isoformat())
        elif splitted[0].lower() == 'yesterday':
            date = today - datetime.timedelta(days=1)
            return str(date.isoformat())
    elif len(splitted) == 3 and splitted[2].lower() == 'ago':
        if splitted[1].lower() in ['day', 'days', 'd']:
            date = today - datetime.timedelta(days=int(splitted[0]))
            return str(date.isoformat())
        elif splitted[1].lower() in ['wk', 'wks', 'week', 'weeks', 'w']:
            date = today - datetime.timedelta(weeks=int(splitted[0]))
            return str(date.isoformat())
        elif splitted[1].lower() in ['yr', 'yrs', 'year', 'years', 'y']:
            date = today.replace(year=today.year - int(splitted[0]))
            return str(date.isoformat())

    try:
        date = datetime.date.fromisoformat(arg)
        return str(date.isoformat())
    except ValueError:
        raise argparse.ArgumentTypeError('invalid <date> format')

def parse_args():
    """Parse the command line argumnets.
    Returns: populated argument namespace.
    """

    parser = argparse.ArgumentParser(prog='gmailtools.py', add_help=False)

    # use add_argument_group() to not display "optional arguments" title

    group1 = parser.add_argument_group()
    group1.add_argument('-h', '--help', action='help',
            default=argparse.SUPPRESS,
            help='show this help message and exit.')
    group1.add_argument('-d', '--debug', action='store_true', dest='debug',
            default=False,
            help='enable debugging')

    group2 = parser.add_argument_group()
    group2.add_argument('--dry-run', action='store_true', dest='dryrun',
            default=False,
            help='run in dry-run mode (do not modify anything)')

    group3 = parser.add_argument_group()
    group3.add_argument('--creds', dest='credsfile', metavar='<file>',
            default=CREDS_FILE,
            help='credentials file to use')
    group3.add_argument('--token', dest='tokenfile', metavar='<file>',
            default=TOKEN_FILE,
            help='saved token file to use')

    subparsers = parser.add_subparsers(prog='gmailtools.py [<opts>]', title='subcommands', dest='subcmd')

    # subcommand: help
    parser_help = subparsers.add_parser('help', add_help=False,
            help='show help message for commands')
    parser_help.add_argument('cmd', nargs='?', metavar='<command>', default=None,
            help=argparse.SUPPRESS)
    parser_help.set_defaults(func=None)

    # subcommand: relabel
    parser_relabel = subparsers.add_parser('relabel', add_help=False,
            help='relabel all messages in a labeled thread (label inheritance)')
    parser_relabel.add_argument('-h', '--help', action='help',
            help=argparse.SUPPRESS)
    parser_relabel.add_argument('--since', type=parse_arg_date, metavar='<date>',
            help='consider threads/messages more recent than a specific date')
    parser_relabel.add_argument('--until', type=parse_arg_date, metavar='<date>',
            help='consider threads/messages less recent than a specific date')
    parser_relabel.add_argument('--label', action='append', metavar='<label>[,..]',
            help='specify labels to consider (default: all user labels)')
    parser_relabel.set_defaults(func=relabel)

    args = parser.parse_args()

    if args.subcmd == 'help':
        if not args.cmd:
            parser.parse_args(['--help'])
        else:
            parser.parse_args([args.cmd, '--help'])
        parser.exit(0)

    if args.subcmd == None:
        parser.print_usage()
        print('{}: error: exactly one subcommand is required'.format(parser.prog))
        parser.exit(1)

    return args

########################################################################
# main

def main():
    args = parse_args()

    global limiter
    limiter = RateLimit(RATE_LIMIT)

    logleveldict = { False: logging.INFO, True: logging.DEBUG }
    loglevel = logleveldict[args.debug]
    logging.basicConfig(level=loglevel, format='%(levelname)s: %(message)s')

    try:
        args.func(args)
    except Exception as e:
        if args.debug:
            raise e
        else:
            logging.error(e)
            logging.error('At: {}'.format(_Context.get()))

if __name__ == '__main__':
    main()

