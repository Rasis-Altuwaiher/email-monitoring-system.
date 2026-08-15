import warnings
from sklearn.exceptions import InconsistentVersionWarning
warnings.filterwarnings("ignore", category=InconsistentVersionWarning)

import configparser
import time
import pickle
import datetime
import sqlite3
import email
import imaplib
import smtplib
import re
import numpy as np

from plyer import notification
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

DATABASE_NAME = "logs.db"


# -------------------- Database --------------------
def setup_database():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            sender_info TEXT,
            subject TEXT,
            classification TEXT,
            size_kb REAL,
            log_type TEXT,
            message_summary TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_to_database(sender, subject, classification, size_kb, log_type, summary):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO email_logs 
        (timestamp, sender_info, subject, classification, size_kb, log_type, message_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, sender, subject, classification, size_kb, log_type, summary))
    conn.commit()
    conn.close()


# -------------------- Statistics --------------------
def get_sender_stats(sender):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM email_logs WHERE sender_info = ?", (sender,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0


def get_message_stats(subject):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM email_logs WHERE subject = ?", (subject,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0


def analyze_keywords(text):
    keywords = ["offer", "free", "winner", "click", "money", "urgent", "verify", "account", "bank"]
    text = text.lower()
    found = [k for k in keywords if k in text]
    return len(found), ", ".join(found)


# -------------------- ML --------------------
def load_model():
    classifier = pickle.load(open("model.pkl", "rb"))
    vectorizer = pickle.load(open("vectorizer.pkl", "rb"))
    return classifier, vectorizer


def classify_email(text, classifier, vectorizer):
    features = vectorizer.transform([text])
    if hasattr(classifier, "predict_proba"):
        score = classifier.predict_proba(features)[0][1] * 100
        label = "Spam" if score > 50 else "NotSpam"
    else:
        label = "Spam" if classifier.predict(features)[0] == 1 else "NotSpam"
        score = 100 if label == "Spam" else 0
    return label, score


# -------------------- Email Utils --------------------
def get_email_body(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode(errors="ignore")
    return ""


def send_email_notification(subject, body, config):
    msg = MIMEMultipart()
    msg["From"] = config["smtp"]["sender_email"]
    msg["To"] = config["smtp"]["receiver_email"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(config["smtp"]["smtp_server"],
                      int(config["smtp"]["smtp_port"])) as server:
        server.starttls()
        server.login(config["smtp"]["sender_email"],
                     config["smtp"]["sender_password"])
        server.send_message(msg)


# -------------------- Main Monitor --------------------
def monitor_inbox():
    setup_database()

    config = configparser.ConfigParser()
    config.read("config.ini")

    classifier, vectorizer = load_model()

    mail = imaplib.IMAP4_SSL(config["imap"]["host"])
    mail.login(config["imap"]["username"], config["imap"]["app_password"])
    mail.select("inbox")

    while True:
        _, messages = mail.search(None, "(UNSEEN)")
        for msg_id in messages[0].split():
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = msg.get("Subject", "No Subject")
            sender = msg.get("From", "Unknown Sender")
            body = get_email_body(msg)

            label, score = classify_email(body, classifier, vectorizer)
            size_kb = len(raw_email) / 1024

            log_to_database(sender, subject, label, size_kb,
                            "CLASSIFICATION", body[:200])

            mail.store(msg_id, "+FLAGS", "\\Seen")

        time.sleep(30)


if __name__ == "__main__":
    monitor_inbox()