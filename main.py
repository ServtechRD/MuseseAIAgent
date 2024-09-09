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

from fastapi import Request, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse

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

import openai

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

# 用户上下文字典
user_context = {}
MAX_CONTEXT_LENGTH = 4096  # 定义最大上下文长度（以字符数为单位）


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


reloadKM()


@app.get("/", response_class=HTMLResponse)
async def main_page():
    files = glob.glob("./docs/*.*")
    files_list_html = "".join([
        f"<li>{os.path.basename(file)} <form style='display:inline;' method='post' action='/delete/'><input type='hidden' name='filename' value='{os.path.basename(file)}'><input type='submit' value='删除'></form></li>"
        for file in files])

    html_content = f"""
    <html>
        <head>
            <title>管理知識庫</title>
            <script type="text/javascript">
                function showLoading() {{
                    document.getElementById("loading").style.display = "block";
                }}
            </script>
        </head>
        <body>
            <h1>上傳文檔並重新生成知識庫</h1>
            <h2>上傳文檔：</h2>
            <form action="/upload/" enctype="multipart/form-data" method="post" onsubmit="showLoading()">
                <input name="file" type="file" required>
                <input type="submit" value="上傳">
            </form>
            <div id="loading" style="display:none;">上傳中，請稍後...</div>
            <h2>当前文档列表：</h2>
            <ul>
                {files_list_html}
            </ul>
            <h2>重新生成知識庫：</h2>
            <form action="/regenerate/" method="post">
                <input type="submit" value="生成知識庫">
            </form>
        </body>
    </html>
    """
    return html_content


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    file_location = f"./docs/{file.filename}"
    with open(file_location, "wb") as f:
        f.write(await file.read())
    naval_chat_bot.add(file_location, data_type='text')
    return RedirectResponse("/", status_code=303)


@app.post("/delete/")
async def delete_file(filename: str = Form(...)):
    file_path = f"./docs/{filename}"
    if os.path.exists(file_path):
        os.remove(file_path)
        naval_chat_bot.reset()  # 清空现有数据库
        reloadKM()  # 重新加载所有文件
    return RedirectResponse("/", status_code=303)


@app.post("/regenerate/")
async def regenerate_db():
    naval_chat_bot.reset()  # 清空现有数据库
    reloadKM()  # 重新加载所有文件
    return RedirectResponse("/", status_code=303)


def trim_context(context: str) -> str:
    """
    修剪上下文，使其保持在最大长度内。
    只保留最新的对话内容。
    """
    if len(context) > MAX_CONTEXT_LENGTH:
        return context[-MAX_CONTEXT_LENGTH:]
    return context


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

        print(event.source.user_id)
        uid = event.source.user_id
        user_input = event.message.text
        user = uid

        # 用户输入 "重置" 或 "清空上下文" 来清空上下文
        if user_input.strip().lower() in ["重置", "清空上下文"]:
            user_context.pop(uid, None)
            await line_bot_api.reply_message(event.reply_token, TextSendMessage(text="上下文已清空。"))
            return 'OK'

        # 如果用户有上下文，合并上下文
        if uid in user_context:
            conversation_history = user_context[uid] + f"\nUser: {user_input}"
        else:
            conversation_history = f"User: {user_input}"

        # 修剪上下文以保持在最大长度内
        conversation_history = trim_context(conversation_history)

        tool_result = naval_chat_bot.query(
            user_input + " reply in zh-tw, result")

        found_data = True

        if not tool_result:
            found_data = False
            # 如果没有找到相关文档，使用GPT-3.5提供答案
            combined_prompt = f"{conversation_history}\n\nAssistant:"
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an assistant"},
                    {"role": "user", "content": combined_prompt},
                ]
            )
            tool_result = response['choices'][0]['message']['content']

            # 保存当前对话的上下文
        user_context[uid] = conversation_history + f"\nAssistant: {tool_result}"

        try:
            profile = await line_bot_api.get_profile(uid)
            user = profile.display_name
        except Exception as e:
            logger.error(e)

        time_text = datetime.now().isoformat()

        output_text = time_text + "|" + uid + "|" + user + "|" + event.message.text + "|" + tool_result + "|" + str(
            found_data)

        logger.info(output_text)

        await line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=tool_result)
        )

    return 'OK'
