# -*- coding: utf-8 -*-
import json
import random
import sys
import time
from hashlib import md5
from os import isatty, environ
import logging
from enum import Enum
from datetime import datetime
from pytwitter import Api
import backoff
import yagmail

from enums.emoji import Emoji
from enums.date_format import DateFormat

MAX_TWEET_LENGTH = 279
DELAY_FILE_TEMPLATE = "next_{}.txt"
DELAY_TIME = 600
CREDENTIALS_FILE = "twitter_credentials.json"
LAST_AVAILABILITY_FILE = "last_availability_data.txt"

class NotificationMethod:
    TWITTER = 1
    EMAIL = 2

LOG = logging.getLogger(__name__)
log_formatter = logging.Formatter(
    "%(asctime)s - %(process)s - %(levelname)s - %(message)s"
)
sh = logging.StreamHandler()
sh.setFormatter(log_formatter)
LOG.addHandler(sh)


def _create_tweet(tweet, tc):
    tweets = split_tweet(tweet)
    
    api = Api(
        consumer_key=tc["consumer_key"],
        consumer_secret=tc["consumer_secret"],
        access_token=tc["access_token_key"],
        access_secret=tc["access_token_secret"],
    )

    for t in tweets:
        _post_tweet(t, api)

def send_email(text_contents):
    gmail_username = environ["BOT_GMAIL_USERNAME"]
    gmail_password = environ["BOT_GMAIL_PASSWORD"]

    if not gmail_username or not gmail_password:
        raise RuntimeError("Gmail username and/or password not set in environment variables")

    yag = yagmail.SMTP(gmail_username, gmail_password)

    to = "s.shamaiengar@gmail.com"
    subject = "New campsites available!"
    contents=text_contents

    yag.send(to=to, subject=subject, contents=contents)

    # TODO: send email with links to campsite pages

    yag.close()

def _post_tweet(tweet, api):
    resp = api.create_tweet(text=tweet)

    LOG.info("Tweet:\n")
    LOG.info(resp)

"""
Break up tweet by lines, then split them into separate 280-char tweets
"""
def split_tweet(tweet):
    tweets = []
    tweet_count = 1
    if len(tweet) > MAX_TWEET_LENGTH:
        tweet_lines = tweet.split("\n")
        current_tweet = f"{tweet_count}/\n"
        for i in range(len(tweet_lines)):
            line = tweet_lines[i]
            if len(line) + len(current_tweet) > MAX_TWEET_LENGTH - 2:
                # split tweet
                tweets.append(current_tweet)
                tweet_count += 1
                current_tweet = f"{tweet_count}/\n"
            current_tweet += line + "\n"
        tweets.append(current_tweet)
    else:
        tweets.append(tweet)
    return tweets

def main(args, stdin):
    with open(CREDENTIALS_FILE) as f:
        tc = json.load(f)

    # Janky simple argument parsing:
    #   python3 notifier.py <usernameToNotify>
    if len(args) < 2:
        print("Please provide the user/email you want to tweet/email at!")
        sys.exit(1)

    notification_method = NotificationMethod.TWITTER

    user = args[1]

    if len(args) == 3:
        if args[2] == "--email":
            notification_method = NotificationMethod.EMAIL
            if "@gmail.com" not in user:
                raise RuntimeError("Email address must contain @gmail.com")

    if (notification_method == NotificationMethod.TWITTER):
        user = args[1].replace("@", "")

    first_line = next(stdin)
    first_line_hash = md5(first_line.encode("utf-8")).hexdigest()

    delay_file = DELAY_FILE_TEMPLATE.format(first_line_hash)
    try:
        with open(delay_file, "r") as f:
            call_time = int(f.read().rstrip())
    except:
        call_time = 0

    if call_time + random.randint(DELAY_TIME - 30, DELAY_TIME + 30) > int(
        time.time()
    ):
        LOG.warning("It is too soon to notify again")
        sys.exit(0)

    if "Something went wrong" in first_line:
        _create_tweet("{}, I'm broken! Please help :'(".format(user), tc)
        sys.exit()

    availability = get_availability_data(stdin)
    available_site_strings = generate_availability_strings_concise(availability)

    last_availability = load_last_availability()

    persist_availability(availability)

    if not has_new_availability(availability, last_availability):
        LOG.warning("No new campsites available, not notifying 😞")
        sys.exit(0)

    if available_site_strings:
        notification_str = generate_tweet_str(available_site_strings, first_line, user)

        LOG.info("Notification (ignoring char limit): \n" + notification_str)

        if notification_method == NotificationMethod.TWITTER:
            _create_tweet(notification_str, tc)
        else:
            send_email(notification_str)

        with open(delay_file, "w") as f:
            f.write(str(int(time.time())))

        sys.exit(0)
    else:
        LOG.warning("No campsites available, not notifying 😞")
        sys.exit(1)


def generate_tweet_str(available_site_strings, first_line, user):
    tweet = "@{}! ".format(user)
    tweet += first_line.rstrip()
    tweet += " 🏕🏕🏕\n"
    tweet += "\n".join(available_site_strings)
    tweet += "\nGo to recreation.gov/camping/campsites/<site#> to reserve."
    return tweet

def generate_availability_strings(stdin):
    available_site_strings = []
    copy_campsite_availability_lines = False
    for line in stdin:
        if Emoji.SUCCESS.value in line:
            line = line.strip() 
            park_name_and_id = " ".join(line.split(":")[0].split(" ")[1:])
            num_available = line.split(":")[1][1].split(" ")[0]
            s = "{} site(s) available in {}".format(
                num_available, park_name_and_id
            )
            available_site_strings.append(s)
            copy_campsite_availability_lines = True
            # get specific site availability from following lines that start with *
        elif copy_campsite_availability_lines:
            # if previous line was SUCCESS, then copy following lines that start with *
            # for specific campsite availability and dates
            if line.strip().startswith("*"):
                available_site_strings.append(line.rstrip())
            else:
                copy_campsite_availability_lines = False
    return available_site_strings

def generate_availability_strings_concise(availability_data):
    strs = []
    if not availability_data:
        return strs

    for p, sites in availability_data.items():
        strs.append(f"{p}:")
        for s, date_ranges in sites.items():
            site_str = f"- Site {s}: "
            for d1, d2 in date_ranges:
                date1 = datetime.strptime(d1, DateFormat.INPUT_DATE_FORMAT.value).strftime("%-m/%-d")
                date2 = datetime.strptime(d2, DateFormat.INPUT_DATE_FORMAT.value).strftime("%-m/%-d")
                site_str += f"{date1}-{date2}, "
            site_str = site_str[:-2]
            strs.append(site_str)
        strs.append("\n")
    return strs
    
# Get availability data as park->site->[(start, end)] from list of input lines
def get_availability_data(stdin):
    # go through stdin to get all lines in a list
    inputs = []
    for l in stdin:
        inputs.append(l)

    availability_by_park = {}
    i = 0
    while i < len(inputs):
        line = inputs[i]
        print("--- " + line + " ---")
        if Emoji.SUCCESS.value in line:
            line = line.strip()
            park_name_and_id = " ".join(line.split(":")[0].split(" ")[1:])
            num_available = int(line.split(":")[1][1].split(" ")[0])
            sites_availability = {}

            # get the availability dates for each site
            for c in range(num_available):
                i += 1
                line = inputs[i].strip()
                try:
                    if "Site" in line:
                        # Get ID from: "* Site 10132102 is ...""
                        site_id = line.split(" ")[2]
                    else:
                        raise RuntimeError("Invalid site ID line")
                except:
                    LOG.warning("Expected <Site #> in line <{line}>")
                
                while "->" in inputs[i+1]:
                    try:
                        i += 1
                        line = inputs[i].strip()
                        # Get dates from "* 2023-08-04 -> 2023-08-06"
                        date1_str = line.split(" ")[1]
                        date2_str = line.split(" ")[3]
                    except:
                        LOG.warning("Expected <YYYY-MM-DD YYYY-MM-DD> in line <{line}>")
                    if site_id not in sites_availability:
                        sites_availability[site_id] = []
                    sites_availability[site_id].append((date1_str, date2_str))
            availability_by_park[park_name_and_id] = sites_availability
        i += 1
    return availability_by_park

def persist_availability(availability_by_park):
    data = json.dumps(availability_by_park)
    with open(LAST_AVAILABILITY_FILE, "w+") as f:
        f.write(data)

def load_last_availability():
    try:
        with open(LAST_AVAILABILITY_FILE, "r") as f:
            last_availability = json.loads(f.read())
            # need to convert lists to tuples to be hashable
            for p, sites in last_availability.items():
                for s, date_ranges in sites.items():
                    sites[s] = tuple(tuple(r) for r in date_ranges)
            return last_availability
    except FileNotFoundError:
        return {}
    
# Compare availabiltiy by park->site->dates to see if any new availability has come up
def has_new_availability(new_data, old_data):
    for p, sites in new_data.items():
        if p not in old_data:
            return True
        for s, date_ranges in sites.items():
            # if new has any new sites for a park
            if s not in old_data[p]:
                return True
            new_dates = set(date_ranges)
            old_dates = set(old_data[p][s])
            # if new has any new dates for a site
            if len(new_dates - old_dates) > 0:
                return True
    return False
            

if __name__ == "__main__":
    LOG.setLevel(logging.DEBUG)
    main(sys.argv, sys.stdin)

"""
Usage:
python3 camping.py --start-date 2023-07-21 --end-date 2023-09-30 --stdin < parks.txt --weekends-only --nights 2 --show-campsite-info | python3 notifier.py @sshamaiengar

python3.9 recreation-gov-campsite-checker/camping.py --start-date 2023-07-21 --end-date 2023-09-30 --stdin < parks.txt --weekends-only --nights 2 --show-campsite-info | python3 recreation-gov-campsite-checker/notifier.py @sshamaiengar
"""
