import pickle
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SECRET_FILE = "/Users/harry2k12/Downloads/client_secret_2_590874069808-urn2f59hlp9u2frgqhio0di1065hg7si.apps.googleusercontent.com.json"
TOKEN_PATH  = "data/youtube_token.pkl"
SCOPES      = ["https://www.googleapis.com/auth/youtube.upload"]

os.makedirs("data", exist_ok=True)

flow  = InstalledAppFlow.from_client_secrets_file(SECRET_FILE, SCOPES)
creds = flow.run_local_server(port=0)

with open(TOKEN_PATH, "wb") as f:
    pickle.dump(creds, f)

print(f"YouTube auth done! Token saved to {TOKEN_PATH}")
