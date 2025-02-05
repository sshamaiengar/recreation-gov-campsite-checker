import logging

import requests
import user_agent
import backoff

from utils import formatter

LOG = logging.getLogger(__name__)
MAX_RETRIES = 5


class RecreationClient:

    BASE_URL = "https://www.recreation.gov"
    AVAILABILITY_ENDPOINT = (
        BASE_URL + "/api/camps/availability/campground/{park_id}/month"
    )
    MAIN_PAGE_ENDPOINT = BASE_URL + "/api/camps/campgrounds/{park_id}"

    headers = {"User-Agent": user_agent.generate_user_agent() }
    
    @classmethod
    def get_availability(cls, park_id, month_date):
        params = {"start_date": formatter.format_date(month_date)}
        LOG.debug(
            "Querying for {} with these params: {}".format(park_id, params)
        )
        url = cls.AVAILABILITY_ENDPOINT.format(park_id=park_id)
        resp = None
        try:
            resp = cls._send_request(url, params)
        except RuntimeError:
            LOG.debug("GET request failed for 5 retries...returning no data")
        return resp

    @classmethod
    def get_park_name(cls, park_id):
        resp = cls._send_request(
            cls.MAIN_PAGE_ENDPOINT.format(park_id=park_id), {}
        )
        return resp["campground"]["facility_name"]

    @classmethod
    @backoff.on_exception(backoff.expo,
                          RuntimeError,
                          max_tries=5,
                          max_time=30,
                          jitter=None)
    def _send_request(cls, url, params):
        resp = requests.get(url, params=params, headers=cls.headers)
        if resp.status_code != 200:
            LOG.debug("GET request failed")
            raise RuntimeError(
                "failedRequest",
                "ERROR, {status_code} code received from {url}: {resp_text}".format(
                    status_code=resp.status_code, url=url, resp_text=resp.text
                ),
            )
        return resp.json()
