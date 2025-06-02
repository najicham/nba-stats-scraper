# scrapers/utils/slack_utils.py

import os
import json
import logging
import tempfile
import pathlib
import shutil
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger("default")


class Slack:
    client = None

    @classmethod
    def get_client(cls):
        """
        Instantiate a singleton Slack WebClient with SLACK_BOT_TOKEN from env.
        Raises ValueError if token is missing.
        """
        if cls.client is None:
            token = os.environ.get("SLACK_BOT_TOKEN", "")
            if not token:
                raise ValueError("SLACK_BOT_TOKEN is not set.")
            cls.client = WebClient(token=token)

    @classmethod
    def get_default_channel(cls):
        """
        Optional: Provide a default Slack channel if none is passed.
        Could read from an env var, e.g. SLACK_DEFAULT_CHANNEL.
        If you do not want a default, remove this method.
        """
        return os.environ.get("SLACK_DEFAULT_CHANNEL", "#general")

    @classmethod
    def send_file(cls, channel=None, title="Slack Upload", data=None, extension="json"):
        """
        Uploads 'data' as a file to Slack in the specified channel.
        If channel is None, falls back to get_default_channel().

        :param channel: Slack channel or user ID (e.g. "#mychannel" or "U12345").
        :param title: Title of the file in Slack.
        :param data: The data to write to a temporary file and upload.
                     Can be a dict, list, str, or bytes.
        :param extension: File extension (e.g. 'json', 'txt') for the temp file.
        """
        cls.get_client()
        if channel is None:
            channel = cls.get_default_channel()

        try:
            # 1) Create a named temp file with chosen extension
            with tempfile.NamedTemporaryFile(
                mode="w+b", delete=False, suffix=f".{extension}"
            ) as tmp_file:
                tmp_path = pathlib.Path(tmp_file.name)

                # 2) Write data to the temp file
                if isinstance(data, (dict, list)):
                    # JSON
                    content = json.dumps(data, indent=4)
                    tmp_file.write(content.encode("utf-8"))
                elif isinstance(data, bytes):
                    # direct bytes
                    tmp_file.write(data)
                else:
                    # string or other
                    tmp_file.write(str(data).encode("utf-8"))

            # 3) Upload the file to Slack
            cls.client.files_upload_v2(
                channels=channel,
                file=str(tmp_path),
                title=title
            )
            logger.info("Slack file uploaded: channel=%s, title=%s, path=%s", channel, title, tmp_path)

        except SlackApiError as e:
            logger.error("SlackApiError while sending file: %s", e)
            raise
        except Exception as exc:
            logger.exception("Unexpected error writing or uploading Slack file.")
            raise
        finally:
            # 4) Cleanup: remove the temp file
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception as cleanup_exc:
                    logger.warning("Failed to remove temp file %s: %s", tmp_path, cleanup_exc)

    @classmethod
    def send_text(cls, channel=None, message=""):
        """
        Sends a simple text message to Slack in the specified channel.
        If channel is None, uses get_default_channel().
        """
        cls.get_client()
        if channel is None:
            channel = cls.get_default_channel()

        try:
            cls.client.chat_postMessage(channel=channel, text=message)
            logger.info("Slack text message sent: channel=%s, message_length=%d", channel, len(message))
        except SlackApiError as e:
            logger.error("SlackApiError while sending text message: %s", e)
            raise
