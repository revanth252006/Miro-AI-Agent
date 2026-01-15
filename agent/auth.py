import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Allow HTTP for local testing
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "web_credentials.json")

SCOPES = [
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive'
]

class AuthManager:
    def __init__(self):
        self.user_sessions = {}

    def get_login_url(self, redirect_uri):
        if not os.path.exists(CLIENT_SECRETS_FILE):
            print(f"❌ Missing {CLIENT_SECRETS_FILE}")
            return "#"
        
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=redirect_uri
        )
        url, _ = flow.authorization_url(access_type='offline', include_granted_scopes='true')
        return url

    def exchange_code(self, code, redirect_uri):
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=redirect_uri
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        service = build('oauth2', 'v2', credentials=creds)
        info = service.userinfo().get().execute()
        
        self.user_sessions[info['id']] = creds
        return info['id'], info['name']

    def get_creds(self, user_id):
        return self.user_sessions.get(user_id)