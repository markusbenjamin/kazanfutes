import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

# Fetch the service account key JSON file contents
cred = credentials.Certificate('firebase_creds.json')

# Initialize the app with a service account, granting admin privileges
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://kazankontroll-database-default-rtdb.europe-west1.firebasedatabase.app'
})

# As an admin, the app has access to read and write all data, regradless of Security Rules
ref = db.reference('test')

# Set the data for the temperature and humidity
ref.set({
    'alma': 22,
    'barack': 45
})