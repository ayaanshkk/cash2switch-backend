# import datetime
# import os.path
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# from google.auth.transport.requests import Request

# # If modifying these SCOPES, delete the token.json file.
# SCOPES = ['https://www.googleapis.com/auth/calendar']

# def get_calendar_service():
#     creds = None
#     if os.path.exists('token.json'):
#         creds = Credentials.from_authorized_user_file('token.json', SCOPES)
#     # If no valid credentials, authenticate
#     if not creds or not creds.valid:
#         if creds and creds.expired and creds.refresh_token:
#             creds.refresh(Request())
#         else:
#             flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
#             creds = flow.run_local_server(port=0)
#         with open('token.json', 'w') as token:
#             token.write(creds.to_json())
#     return build('calendar', 'v3', credentials=creds)

# def create_calendar_event(assignment):
#     service = get_calendar_service()

#     event = {
#         'summary': assignment.title,
#         'description': assignment.notes,
#         'start': {
#             'dateTime': f"{assignment.date}T{assignment.start_time or '09:00:00'}",
#             'timeZone': 'Europe/London',
#         },
#         'end': {
#             'dateTime': f"{assignment.date}T{assignment.end_time or '17:00:00'}",
#             'timeZone': 'Europe/London',
#         },
#     }

#     event = service.events().insert(calendarId='primary', body=event).execute()
#     return event.get('id')

# def update_calendar_event(event_id, assignment):
#     service = get_calendar_service()
#     event = service.events().get(calendarId='primary', eventId=event_id).execute()

#     event['summary'] = assignment.title
#     event['description'] = assignment.notes
#     event['start']['dateTime'] = f"{assignment.date}T{assignment.start_time or '09:00:00'}"
#     event['end']['dateTime'] = f"{assignment.date}T{assignment.end_time or '17:00:00'}"

#     updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
#     return updated_event.get('id')

# def delete_calendar_event(event_id):
#     service = get_calendar_service()
#     service.events().delete(calendarId='primary', eventId=event_id).execute()
