# -*- coding: utf-8 -*-
"""
Miro Google Calendar Integration — Create and read events using Google Calendar API.
Requires Google OAuth to be set up (web_credentials.json).
"""

import asyncio
import datetime
import re

try:
    from googleapiclient.discovery import build
    GCAL_API_AVAILABLE = True
except ImportError:
    GCAL_API_AVAILABLE = False


async def get_todays_events(credentials) -> str:
    """Fetches today's events from Google Calendar."""
    if not GCAL_API_AVAILABLE or not credentials:
        return "Google Calendar not configured. Need Google OAuth login first."
    
    loop = asyncio.get_running_loop()
    
    def _fetch():
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.datetime.utcnow()
        start = now.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
        end = now.replace(hour=23, minute=59, second=59).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        if not events:
            return "### 📅 Today's Schedule\nNo events scheduled for today. You're free!"
        
        lines = ["### 📅 Today's Schedule\n"]
        lines.append("| Time | Event |")
        lines.append("|------|-------|")
        for event in events:
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            if 'T' in start_time:
                time_str = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00')).strftime('%I:%M %p')
            else:
                time_str = "All Day"
            lines.append(f"| {time_str} | {event.get('summary', 'Untitled')} |")
        
        return "\n".join(lines)
    
    return await loop.run_in_executor(None, _fetch)


async def create_event(credentials, title: str, start_time: datetime.datetime, 
                       duration_hours: int = 1) -> str:
    """Creates a Google Calendar event."""
    if not GCAL_API_AVAILABLE or not credentials:
        return "Google Calendar not configured. Need Google OAuth login first."
    
    loop = asyncio.get_running_loop()
    
    def _create():
        service = build('calendar', 'v3', credentials=credentials)
        end_time = start_time + datetime.timedelta(hours=duration_hours)
        
        event = {
            'summary': title,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
        }
        
        created = service.events().insert(calendarId='primary', body=event).execute()
        return f"✅ Event created: **{title}** at {start_time.strftime('%I:%M %p on %B %d')}"
    
    return await loop.run_in_executor(None, _create)


def parse_schedule_command(text: str) -> dict | None:
    """Parses 'schedule meeting with X tomorrow at 3pm' into event data."""
    patterns = [
        r'schedule\s+(?:a\s+)?(.+?)\s+(?:on\s+)?(?:tomorrow|today)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
        r'schedule\s+(?:a\s+)?(.+?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:tomorrow|today)',
        r'schedule\s+(?:a\s+)?(.+?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
    ]
    
    t = text.lower()
    for pat in patterns:
        match = re.search(pat, t)
        if match:
            title = match.group(1).strip().title()
            time_str = match.group(2).strip()
            
            # Parse the time
            try:
                if 'pm' in time_str or 'am' in time_str:
                    parsed_time = datetime.datetime.strptime(time_str, '%I %p' if ':' not in time_str else '%I:%M %p')
                else:
                    parsed_time = datetime.datetime.strptime(time_str, '%H' if ':' not in time_str else '%H:%M')
            except ValueError:
                continue
            
            # Determine date
            event_date = datetime.date.today()
            if 'tomorrow' in t:
                event_date += datetime.timedelta(days=1)
            
            event_datetime = datetime.datetime.combine(event_date, parsed_time.time())
            
            return {
                'title': title,
                'datetime': event_datetime,
            }
    
    return None
