import base64
from googleapiclient.discovery import build
from email.mime.text import MIMEText

class GoogleTools:
    def __init__(self, auth_manager):
        self.auth = auth_manager

    def _get_service(self, user_id, service, version):
        creds = self.auth.get_creds(user_id)
        if not creds: return None
        return build(service, version, credentials=creds)

    def check_emails(self, user_id):
        service = self._get_service(user_id, 'gmail', 'v1')
        if not service: return "Login required."
        try:
            results = service.users().messages().list(userId='me', labelIds=['INBOX'], q="is:unread", maxResults=3).execute()
            messages = results.get('messages', [])
            if not messages: return "No unread emails."
            summary = []
            for msg in messages:
                txt = service.users().messages().get(userId='me', id=msg['id']).execute()
                headers = txt['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
                summary.append(f"From: {sender} | Subject: {subject}")
            return "\n".join(summary)
        except Exception as e: return f"Gmail Error: {str(e)}"

    def send_email(self, user_id, to, subject, body):
        service = self._get_service(user_id, 'gmail', 'v1')
        if not service: return "Login required."
        try:
            msg = MIMEText(body)
            msg['to'] = to
            msg['subject'] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId='me', body={'raw': raw}).execute()
            return f"Email sent to {to}."
        except Exception as e: return f"Send Error: {str(e)}"

    def create_doc(self, user_id, title, content):
        service = self._get_service(user_id, 'docs', 'v1')
        if not service: return "Login required."
        try:
            doc = service.documents().create(body={'title': title}).execute()
            doc_id = doc.get('documentId')
            requests = [{'insertText': {'location': {'index': 1}, 'text': content}}]
            service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()
            return f"Created document '{title}'."
        except Exception as e: return f"Doc Error: {str(e)}"