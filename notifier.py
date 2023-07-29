# -*- coding: utf-8 -*-
import json
import random
import sys
import time
from hashlib import md5
from os import isatty, environ, path
import glob
import logging
from enum import Enum
from datetime import datetime, timedelta
from pytwitter import Api, PyTwitterError
import backoff
import yagmail

from enums.emoji import Emoji
from enums.date_format import DateFormat

MAX_TWEET_LENGTH = 279
DELAY_FILE_TEMPLATE = "next_{}.txt"
DELAY_TIME = 120
CREDENTIALS_FILE = "twitter_credentials.json"
LAST_AVAILABILITY_FILE_PREFIX = "last_availability_data_"
LAST_AVAILABILITY_FILE_SUFFIX = ".txt"
LAST_AVAILABILITY_DATA_TTL = timedelta(hours=12)

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

    # post multiple tweets in one thread
    last_tweet_id = None
    for t in tweets:
        resp = _post_tweet(t, api, last_tweet_id)
        if resp:
            last_tweet_id = resp.id

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

def _post_tweet(tweet, api: Api, reply_tweet_id=None):
    resp = None
    try:
        if not reply_tweet_id:
            resp = api.create_tweet(text=tweet)
        else:
            resp = api.create_tweet(text=tweet,
                                reply_in_reply_to_tweet_id=reply_tweet_id,
                                reply_exclude_reply_user_ids=[])
    except PyTwitterError as e:
        LOG.error(f"Posting tweet failed with exception: {e.message}")

    LOG.info("Tweet:\n")
    LOG.info(resp)
    return resp

def format_user_mentions(users):
    mention_strs = ["@" + u for u in users]
    return " ".join(mention_strs)

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

    users = args[1]

    if len(args) == 3:
        if args[2] == "--email":
            notification_method = NotificationMethod.EMAIL
            if "@gmail.com" not in users:
                raise RuntimeError("Email address must contain @gmail.com")

    if (notification_method == NotificationMethod.TWITTER):
        users = args[1].replace("@", "")
        users = users.split(",")

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
        _create_tweet("{}, I'm broken! Please help :'(".format(format_user_mentions(users)), tc)
        sys.exit()

    availability = get_availability_data(stdin)
    available_site_strings = generate_availability_strings_concise(availability)

    last_availability = load_last_availability()

    persist_availability(availability)

    if not has_new_availability(availability, last_availability):
        LOG.warning("No new campsites available, not notifying 😞")
        sys.exit(0)

    if available_site_strings:
        notification_str = generate_tweet_str(available_site_strings, first_line, users)

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


def generate_tweet_str(available_site_strings, first_line, users):
    tweet = "{}! ".format(format_user_mentions(users))
    tweet += first_line.rstrip()
    # prevent duplicate tweets with random emoji count
    tweet += " " + "🏕" * random.randint(3, 10) + "\n\n"
    tweet += "\n".join(available_site_strings)
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
            site_str = f"Site {s} (recreation.gov/camping/campsites/{s}):\n"
            for d1, d2 in date_ranges:
                date1 = datetime.strptime(d1, DateFormat.INPUT_DATE_FORMAT.value).strftime("%-m/%-d")
                date2 = datetime.strptime(d2, DateFormat.INPUT_DATE_FORMAT.value).strftime("%-m/%-d")
                site_str += f"{date1}-{date2}, "
            site_str = site_str[:-2]
            strs.append(site_str + "\n")
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

def get_last_availability_file_name_and_time():
    # find most recent availability file
    availability_files = glob.glob(f"./{LAST_AVAILABILITY_FILE_PREFIX}*")
    if not availability_files:
        return None, datetime.min
    last_availability_file = max(availability_files, key=path.getctime)

    # get timestamp out of filename ./last_availability_data_<timestamp>.txt
    last_availability_time_str = last_availability_file.split("/")[-1].split(".")[0].split("_")[3]
    last_availability_time: datetime = datetime.now()
    try:
        last_availability_time = datetime.strptime(last_availability_time_str, "%Y%m%d-%H%M%S")
    except:
        LOG.warning(f"Unable to parse datetime from <{last_availability_time_str}>")

    return last_availability_file, last_availability_time

def persist_availability(availability_by_park):
    data = json.dumps(availability_by_park)

    # look for a previous availability file within TTL
    # If exists, update it (keeping same time)
    last_availability_file, last_availability_time = get_last_availability_file_name_and_time()
    last_availability_delta = datetime.now() - last_availability_time
    availability_file_to_write = last_availability_file
    if last_availability_delta > LAST_AVAILABILITY_DATA_TTL:
        availability_file_to_write = LAST_AVAILABILITY_FILE_PREFIX + datetime.now().strftime("%Y%m%d-%H%M%S") + LAST_AVAILABILITY_FILE_SUFFIX
    else:
        LOG.info(f"Will update last availability data from {last_availability_delta.total_seconds() / 60} minutes ago")

    with open(availability_file_to_write, "w+") as f:
        f.write(data)

def load_last_availability():
    try:
        last_availability_file, last_availability_time = get_last_availability_file_name_and_time()

        # if last availability data is past TTL, ignore it
        last_availability_delta = datetime.now() - last_availability_time
        if last_availability_delta > LAST_AVAILABILITY_DATA_TTL:
            return {}
        else:
            LOG.info(f"Found last availability data from {last_availability_delta.total_seconds() / 60} minutes ago")

        with open(last_availability_file, "r") as f:
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
