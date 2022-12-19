import abc
import io
import json
import logging
import math
import re
import time
import asyncio

from datetime import datetime
from pathlib import Path
from typing import *
from pyChatGPT import ChatGPT
from gists import File as GistFile
from gists import Client as GistClient

from .bot_request_handler import BotRequestHandler
from .bot_request_context import BotRequestContext
from .proc_args_context import ProcArgsContext

async def upload_gist(client, question, body):
    files = [
        GistFile(name="answer-" + str(int(time.time())) + ".md", content=body),
    ]

    return await client.create_gist(files=files, description="Answer from ChatGPT requested by user - " + question, public=False)

class ChatGptHandler(BotRequestHandler):
    def __init__(self,
                pipe:ChatGPT,
                gist:GistClient,
                tag_name: str = 'ask',
                allow_self_request_only: bool = False
                ):
        self.pipe = pipe
        self.gist = gist
        self.tag_name = tag_name
        self.allow_self_request_only = allow_self_request_only
        self.re_strip_special_token = re.compile(r'<\|.*?\|>')

    def is_eligible_for(self, ctx: BotRequestContext) -> bool:
        contains_hash = ctx.contains_tag_name(self.tag_name)
        if not contains_hash:
            return False

        return (
            ( ctx.mentions_bot() and ctx.not_from_self() and not self.allow_self_request_only)
            or
            not ctx.not_from_self()
        )

    def respond_to(self, ctx: BotRequestContext, args_ctx: ProcArgsContext) -> bool:
        talk = args_ctx.prompts['positive']
        in_progress_status = ctx.reply_to(ctx.status, '처리중...', keep_context=False)

        if 'num_inference_steps' in args_ctx.proc_kwargs \
            and args_ctx.proc_kwargs['num_inference_steps'] is not None:
            args_ctx.proc_kwargs['num_inference_steps'] = int(args_ctx.proc_kwargs['num_inference_steps'])
        
        logging.info('sending request to chatgpt...')
        status = "done"

        try:
            raw_result = self.pipe.send_message(talk)
            result = raw_result['message']
        except Exception:
            try:
                logging.info('error, retry one more time after 20 second...')
                time.sleep(10)
                self.pipe.reset_conversation()
                time.sleep(10)
                raw_result = self.pipe.send_message(talk + ", in korean")
                result = raw_result['message']
            except Exception as general_error:
                if "InvalidChunkLength" in str(general_error):
                    result = "AI가 대답하는데 너무 오래 걸렸습니다. 좀 더 단순한 질문을 해보세요."
                    status = "timeout"
                elif "Status code 401" in str(general_error):
                    result = "토큰이 만료되었습니다. @yumeka@twingyeo.kr"
                    status = "expired"
                elif "Too many requests" in str(general_error):
                    result = "API 사용 제한 상태. 잠시후 다시 요청해주세요."
                    status = "error"
                else:
                    result = "오류 발생. 다시 시도해 보세요.\n\n" + str(general_error)
                    status = "error"
        
        logging.info(f'building reply text')
        try:
            gist = asyncio.run(upload_gist(self.gist, talk, result))
            url = gist.url
            logging.info(url)
        except Exception as e:
            logging.error(e)
            url = "pastebin 업로드 실패"
        
        if len(result) > 450:
            result = result[0:350] + "...\n\n" + url
            
        
        if len(talk) > 20:
            reply_message, spoiler_text = [result, "[" + status + "] " + talk[0:20] + "..."]
        else:
            reply_message, spoiler_text = [result, "[" + status + "] " + talk]
        
        behavior_conf = ctx.bot_ctx.behavior_conf

        reply_target_status = ctx.status if behavior_conf.delete_processing_message else in_progress_status

        replied_status = ctx.reply_to(
            reply_target_status,
            reply_message,
            visibility=ctx.reply_visibility,
            spoiler_text=spoiler_text,
            sensitive=True,
            tag_behind=behavior_conf.tag_behind_on_image_post
        )

        if behavior_conf.tag_behind_on_image_post:
            ctx.mastodon.status_reblog(replied_status['id'])

        if behavior_conf.delete_processing_message:
            ctx.mastodon.status_delete(in_progress_status)

        logging.info('sent')

        return True

    def reply_in_progress(self, ctx: BotRequestContext, args_ctx: ProcArgsContext, positive_input_form: str, negative_input_form: Optional[str]):
        processing_body = ""
        in_progress_status = ctx.reply_to(status=ctx.status,
                                          body=processing_body if len(processing_body) > 0 else '처리중...',
                                          spoiler_text='처리중...' if len(processing_body) > 0 else None,
                                          keep_context=True if len(processing_body) > 0 else False
                                          )
        return in_progress_status
