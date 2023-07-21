# -*- coding: utf-8 -*-
import json
import random
import sys
import time
from hashlib import md5
from os import isatty
import logging

import twitter

from enums.emoji import Emoji

MAX_TWEET_LENGTH = 279
DELAY_FILE_TEMPLATE = "next_{}.txt"
DELAY_TIME = 600
CREDENTIALS_FILE = "twitter_credentials.json"
LAST_TWEET_FILE = "last_tweet.txt"

LOG = logging.getLogger(__name__)
log_formatter = logging.Formatter(
    "%(asctime)s - %(process)s - %(levelname)s - %(message)s"
)
sh = logging.StreamHandler()
sh.setFormatter(log_formatter)
LOG.addHandler(sh)


def _create_tweet(tweet, tc):
    tweet = tweet[:MAX_TWEET_LENGTH]
    api = twitter.Api(
        consumer_key=tc["consumer_key"],
        consumer_secret=tc["consumer_secret"],
        access_token_key=tc["access_token_key"],
        access_token_secret=tc["access_token_secret"],
    )
    resp = api.PostUpdate(tweet)
    # api.CreateFavorite(resp)
    print("The following was tweeted: ")
    print()
    print(tweet)


def main(args, stdin):
    with open(CREDENTIALS_FILE) as f:
        tc = json.load(f)

    # Janky simple argument parsing.
    if len(args) != 2:
        print("Please provide the user you want to tweet at!")
        sys.exit(1)

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
        LOG.warn("It is too soon to tweet again")
        sys.exit(0)

    if "Something went wrong" in first_line:
        _create_tweet("{}, I'm broken! Please help :'(".format(user), tc)
        sys.exit()

    available_site_strings = generate_availability_strings(stdin)

    if available_site_strings:
        tweet = generate_tweet_str(available_site_strings, first_line, user)
        last_tweet = ""

        try:
            with open(LAST_TWEET_FILE, "r") as f:
                last_tweet = f.read()
        except FileNotFoundError:
            pass

        # check last tweet contents. if the same, then don't tweet again.
        # otherwise, tweet and save the text again
        if tweet == last_tweet:
            LOG.warn("No change in available campsites, not tweeting")
            sys.exit(0)
        else:
            LOG.info("Tweet: \n" + tweet)
            # _create_tweet(tweet, tc)
            # with open(delay_file, "w") as f:
            #     f.write(str(int(time.time())))
            with open(LAST_TWEET_FILE, "w+") as f:
                f.write(tweet)
            sys.exit(0)
    else:
        LOG.warn("No campsites available, not tweeting 😞")
        sys.exit(1)


def generate_tweet_str(available_site_strings, first_line, user):
    tweet = "@{}!!! ".format(user)
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


if __name__ == "__main__":
    LOG.setLevel(logging.DEBUG)
    main(sys.argv, sys.stdin)

"""
Usage:
python3 camping.py --start-date 2023-07-21 --end-date 2023-08-30 --stdin < parks.txt --weekends-only --nights 2 --show-campsite-info | python3 notifier.py @sshamaiengar
"""
