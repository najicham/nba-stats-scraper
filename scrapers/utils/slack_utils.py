# scrapers/utils/slack_utils.py

import os
import json
import logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger("default")

class Slack:
    client = None

    @classmethod
    def get_client(cls):
        if cls.client is None:
            token = os.environ.get("SLACK_BOT_TOKEN", "")
            if not token:
                raise ValueError("SLACK_BOT_TOKEN is not set.")
            cls.client = WebClient(token=token)

    @classmethod
    def send_file(cls, channel, title, data):
        """
        Uploads 'data' as a file to Slack in specified channel.
        """
        try:
            cls.get_client()
            tmp_file = "/tmp/slack_upload.json"
            with open(tmp_file, "w") as f:
                if isinstance(data, (dict, list)):
                    json.dump(data, f, indent=4)
                else:
                    f.write(str(data))

            cls.client.files_upload_v2(
                channels=channel,
                file=tmp_file,
                title=title,
            )
        except SlackApiError as e:
            logger.error(f"Slack error: {e}")
            raise

    @classmethod
    def send_text(cls, channel, message):
        try:
            cls.get_client()
            cls.client.chat_postMessage(
                channel=channel,
                text=message
            )
        except SlackApiError as e:
            logger.error(f"Slack error: {e}")
            raise
