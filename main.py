# from __future__ import print_function
import datetime
import os.path
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
import logging as log
import sys

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/contacts.readonly']


def main():
    log.info("VVF SMS starting...")

    # Load SMSMODE API key
    with open("./smsmode_api_key.txt") as f:
        sms_api_key = f.read()

    # Load Google credentials
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        # Get contacts from the People API
        log.info('Getting contacts...')
        people_service = build('people', 'v1', credentials=creds)
        people = people_service.people().connections().list(
            resourceName='people/me',
            personFields='emailAddresses,phoneNumbers').execute()
        connections = people.get('connections', [])
        people = {}
        for person in connections:
            email = person.get('emailAddresses', [])
            if email:
                email = email[0].get('value')
            phone = person.get('phoneNumbers', [])
            if phone:
                phone = phone[0].get('value')
                if phone[0:3] != "+39":
                    phone = "+39"+phone
            if email and phone:
                people[email] = phone.replace(" ", "")

        # Get upcoming events from the Calendar API
        cal_service = build('calendar', 'v3', credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
        tomorrow = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + 'Z'  # 'Z' indicates UTC time
        log.info('Getting upcoming events...')
        events_result = cal_service.events().list(calendarId='primary', timeMin=now, timeMax=tomorrow,
                                                  singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            log.info('No upcoming events found.')
            return

        # Process events
        for event in events:
            time.sleep(1)
            start = event['start'].get('dateTime', event['start'].get('date'))
            if _needs_reminder(event):
                log.info(f"Sending reminders for event {start} {event['summary']}")
                _send_sms_reminders(event, people, sms_api_key)
                _set_reminded(event, cal_service)
            else:
                log.info(f"Skipping event {start} {event['summary']}")

    except HttpError as error:
        log.error('An error occurred: %s' % error)

    log.info('Done.')


def _needs_reminder(event):
    if event['summary'] == "TESTSMS":
        return True
    if 'description' in event and 'REMINDED' in event['description']:
        return False
    if event['summary'] in ['Servizio Notturno', 'Servizio Festivo', 'Servizio Sabato']:
        return True
    if 'Reperibilità' in event['summary']:
        return True
    if 'RIUNIONE' in event['summary'].upper():
        return True
    if 'ASSEMBLEA' in event['summary'].upper():
        return True
    if 'MANOVRA' in event['summary'].upper():
        return True
    return False


def _send_sms_reminders(event, people, api_key):
    if 'attendees' not in event:
        return
    for attendee in event['attendees']:
        if 'organizer' in attendee and attendee['organizer']:
            # Do not remind the organizer - service account
            continue
        email = attendee['email']

        if email not in people:
            log.warning(f"Did not send SMS to '{email}' as I do not have the phone number.")
            return

        phone = people[email]
        msg = f"Ricordati dell'evento '{event['summary']}' il {_start_date(event)} alle {_start_time(event)}."
        headers = {
            'Accept': 'application/json',
            'Content-type': 'application/json',
            'X-Api-Key': api_key,
        }
        body = {
            "recipient": {"to": phone},
            "body": {"text": msg}
        }
        r = requests.post("https://rest.smsmode.com/sms/v1/messages", json=body, headers=headers)
        if r.status_code in [200, 201]:
            log.info(f"Sent SMS request for '{msg}' to '{email} at {phone}.")
            log.debug(f"Response:{r.text}")
        else:
            log.error(f"Error in sending SMS to '{email} at {phone}: {r.status_code} {r.reason}{r.text}")
    return


def _set_reminded(event, cal_service):
    description = 'REMINDED'
    if 'description' in event:
        description = 'REMINDED | ' + event['description']
    event['description'] = description
    updated_event = cal_service.events().update(calendarId='primary', eventId=event['id'], body=event,
                                                sendUpdates='none').execute()
    return


def _get_start_datetime(event):
    return datetime.datetime.fromisoformat(event['start'].get('dateTime'))


def _start_date(event):
    dt = _get_start_datetime(event)
    return dt.strftime("%d/%m/%Y")


def _start_time(event):
    dt = _get_start_datetime(event)
    return dt.strftime("%H:%M")


if __name__ == '__main__':
    log.basicConfig(filename='vvf_sms.log', encoding='utf-8', level=log.DEBUG, format='%(asctime)s %(message)s')
    log.getLogger().addHandler(log.StreamHandler(sys.stdout))
    main()
