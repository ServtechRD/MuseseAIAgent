"""
This is a FastAPI app that serves as a webhook for LINE Messenger.
It uses the embedchain library to handle incoming messages and generate appropriate responses.
"""
# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import sys
import glob

import loguru

import aiohttp

from fastapi import Request, FastAPI, HTTPException

from embedchain import App
from embedchain.store.assistants import AIAssistant

from linebot import (
    AsyncLineBotApi, WebhookParser
)
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
)

from dotenv import load_dotenv, find_dotenv

from datetime import datetime, timezone, timedelta

from loguru import logger

_ = load_dotenv(find_dotenv())  # read local .env file

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('ChannelSecret', None)
channel_access_token = os.getenv('ChannelAccessToken', None)
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)


def reloadKM():
    dir = "./docs"

    files = glob.glob(dir + "/*.*")

    for file in files:
        try:
            print("found :" + file)
            ext = file[-4:]
            print("ext = " + ext)
            if (ext == '.pdf'):
                print("is pdf file")
                naval_chat_bot.add(file, data_type='pdf_file')
            elif (ext == '.txt'):
                print("is text file")
                naval_chat_bot.add(file, data_type='text')
            elif (ext == '.docx'):
                print("is docx file")
                naval_chat_bot.add(file, data_type='docx')
        except Exception as e:
            print("Add KM Error reaseon : $e")


if not os.path.exists("./log"):
    os.makedirs("./log")
logger.add("./logs/linebot.log", rotation="12:00", retention="14 days", compression="zip")

app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

# Embedchain App
naval_chat_bot = App.from_config(yaml_path="config.yaml")

reloadKM()

# Add tools to the app
'''
naval_chat_bot.add(
    "web_page", "https://tw.linebiz.com/column/LINEOA-2023-Price-Plan/")

naval_chat_bot.add(
    "web_page", "https://tw.linebiz.com/column/stepmessage/")

naval_chat_bot.add(
    "web_page", "https://tw.linebiz.com/column/LAP-Maximize-OA-Strategy/")
'''


@app.get("/test")
async def handle_test(mode, message):
    # get request body as text

    print(message)
    print(mode)

    result = ""

    if mode == "0":
        result = naval_chat_bot.chat(
            message + " reply in zh-tw, result")
    elif mode == "1":
        result = naval_chat_bot.query(
            message + " reply in zh-tw, result", citations=False)
    else:
        result = naval_chat_bot.chat(
            message + " reply in zh-tw, result", citations=True)

    print(result)

    return result


@app.post("/callback")
async def handle_callback(request: Request):
    """
    Handle the callback from LINE Messenger.

    This function validates the request from LINE Messenger, 
    parses the incoming events and sends the appropriate response.

    Args:
        request (Request): The incoming request from LINE Messenger.

    Returns:
        str: Returns 'OK' after processing the events.
    """
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid signature") from exc

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        if not isinstance(event.message, TextMessage):
            continue

        tool_result = naval_chat_bot.query(
            event.message.text + " reply in zh-tw, result")

        uid = event.source.userId
        user = uid
        try:
            profile = line_bot_api.get_profile(uid)
            user = profile.displayName
        except LineBotApiError as e:
            logger.error(e)

        time_text = datetime.now().isoformat()

        output_text = time_text + "|" + uid + "|" + user + "|" + event.message.text + "|" + tool_result

        logger.info(output_text)

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=tool_result)
        )

    return 'OK'
