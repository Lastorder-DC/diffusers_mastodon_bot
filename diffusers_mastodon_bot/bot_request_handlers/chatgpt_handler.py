import abc
import io
import json
import logging
import math
import re
import time

from datetime import datetime
from pathlib import Path
from typing import *
from pyChatGPT import ChatGPT
from pbwrap import Pastebin

from .bot_request_handler import BotRequestHandler
from .bot_request_context import BotRequestContext
from .proc_args_context import ProcArgsContext


class ChatGptHandler(BotRequestHandler):
    def __init__(self,
                pipe:ChatGPT,
                pastebin:Pastebin,
                tag_name: str = 'ask',
                allow_self_request_only: bool = False
                ):
        self.pipe = pipe
        self.pastebin = pastebin
        self.tag_name = tag_name
        self.allow_self_request_only = allow_self_request_only
        self.re_strip_special_token = re.compile('<\|.*?\|>')

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
        in_progress_status = ctx.reply_to(ctx.status, 'processing...', keep_context=False)

        if 'num_inference_steps' in args_ctx.proc_kwargs \
            and args_ctx.proc_kwargs['num_inference_steps'] is not None:
            args_ctx.proc_kwargs['num_inference_steps'] = int(args_ctx.proc_kwargs['num_inference_steps'])
        
        logging.info(f'sending request to chatgpt...')
        status = "done"

        try:
            raw_result = self.pipe.send_message(talk)
            result = raw_result['message']
        except:
            try:
                logging.info(f'error, retry one more time after 10 second...')
                time.sleep(10)
                raw_result = self.pipe.send_message(talk)
                result = raw_result['message']
            except Exception as e:
                if "InvalidChunkLength" in str(e):
                    result = "AI가 대답하는데 너무 오래 걸렸습니다. 좀 더 단순한 질문을 해보세요."
                    status = "timeout"
                elif "Status code 401" in str(e):
                    result = "토큰이 만료되었습니다. @yumeka@twingyeo.kr"
                    status = "expired"
                else:
                    result = "오류 발생. 다시 시도해 보세요.\n\n" + str(e)
                    status = "error"
        
        logging.info(f'building reply text')
        
        if len(result) > 400:
            try:
                url = self.pastebin.create_paste(result, 1, "[bot ask] " + talk, "N")
                result = result[0:300] + "...\n\n" + url
            except Exception as e:
                result = "답변이 길지만 pastebin에 업로드할수 없었습니다.\n\n" + str(e)
        
        if len(talk) > 20:
            reply_message, spoiler_text = [result, "[" + status + "] " + talk[0:20] + "..."]
        else:
            reply_message, spoiler_text = [result, "[" + status + "] " + talk]
        reply_target_status = ctx.status if ctx.bot_ctx.delete_processing_message else in_progress_status

        replied_status = ctx.reply_to(
            reply_target_status,
            reply_message,
            visibility=ctx.reply_visibility,
            spoiler_text=spoiler_text,
            sensitive=True,
            tag_behind=ctx.bot_ctx.tag_behind_on_image_post
        )

        if ctx.bot_ctx.tag_behind_on_image_post:
            ctx.mastodon.status_reblog(replied_status['id'])

        if ctx.bot_ctx.delete_processing_message:
            ctx.mastodon.status_delete(in_progress_status)

        logging.info(f'sent')

        return True

    def reply_in_progress(self, ctx: BotRequestContext, args_ctx: ProcArgsContext, positive_input_form: str, negative_input_form: Optional[str]):
        processing_body = ""
        in_progress_status = ctx.reply_to(status=ctx.status,
                                          body=processing_body if len(processing_body) > 0 else '처리중...',
                                          spoiler_text='처리중...' if len(processing_body) > 0 else None,
                                          keep_context=True if len(processing_body) > 0 else False
                                          )
        return in_progress_status
