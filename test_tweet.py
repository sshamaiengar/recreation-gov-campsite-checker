# -*- coding: utf-8 -*-
import json
import random
import sys
import time
from hashlib import md5
from os import isatty, environ
import logging
from enum import Enum

from pytwitter import Api
import backoff

MAX_TWEET_LENGTH = 279
CREDENTIALS_FILE = "twitter_credentials.json"

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

def _post_tweet(tweet, api):
    resp = api.create_tweet(text=tweet)

    print("The following was tweeted: ")
    print()
    print(tweet)

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

if __name__ == "__main__":
    with open(CREDENTIALS_FILE) as f:
        tc = json.load(f)
    
    twt = "Test tweet @sshamaiengar"

    _create_tweet(twt, tc)