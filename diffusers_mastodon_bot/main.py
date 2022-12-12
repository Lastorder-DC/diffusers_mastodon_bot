import logging
import sys
from pathlib import Path
from typing import *
import json

from mastodon import Mastodon

import torch

from diffusers.pipelines.stable_diffusion import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline

from diffusers_mastodon_bot.app_stream_listener import AppStreamListener
from diffusers_mastodon_bot.bot_request_handlers.bot_request_handler import BotRequestHandler
from diffusers_mastodon_bot.bot_request_handlers.game.diffuse_game_handler import DiffuseGameHandler
from diffusers_mastodon_bot.bot_request_handlers.diffuse_me_handler import DiffuseMeHandler
from diffusers_mastodon_bot.bot_request_handlers.diffuse_it_handler import DiffuseItHandler
from diffusers_mastodon_bot.community_pipeline.lpw_stable_diffusion \
    import StableDiffusionLongPromptWeightingPipeline as StableDiffusionLpw


def create_diffusers_pipeline(device_name='cuda', pipe_kwargs: Optional[Dict[str, Any]] = None):
    if pipe_kwargs is None:
        pipe_kwargs = {}

    pipe_kwargs = pipe_kwargs.copy()

    kwargs_defaults = {
        "pretrained_model_name_or_path": 'hakurei/waifu-diffusion',
        'revision': 'fp16'
    }

    for key, value in kwargs_defaults.items():
        if key not in pipe_kwargs:
            pipe_kwargs[key] = value

    model_name_or_path = pipe_kwargs['pretrained_model_name_or_path']
    del pipe_kwargs['pretrained_model_name_or_path']

    torch_dtype = torch.float32
    if 'torch_dtype' in pipe_kwargs:
        dtype_param = pipe_kwargs['torch_dtype']
        del pipe_kwargs['torch_dtype']

        if dtype_param == 'torch.float16':
            torch_dtype = torch.float16

    if 'scheduler' in pipe_kwargs:
        scheduler_param = pipe_kwargs['scheduler']
        del pipe_kwargs['scheduler']

        if scheduler_param == 'euler':
            from diffusers import EulerDiscreteScheduler
            pipe_kwargs['scheduler'] = EulerDiscreteScheduler.from_pretrained(model_name_or_path, subfolder="scheduler")
        elif scheduler_param == 'euler_a':
            from diffusers import EulerAncestralDiscreteScheduler
            pipe_kwargs['scheduler'] = EulerAncestralDiscreteScheduler.from_pretrained(model_name_or_path,
                                                                                       subfolder="scheduler")
        elif scheduler_param == 'dpm_solver++':
            from diffusers import DPMSolverMultistepScheduler
            pipe_kwargs['scheduler'] = DPMSolverMultistepScheduler.from_pretrained(model_name_or_path,
                                                                                   subfolder="scheduler")

    pipe: StableDiffusionLpw = StableDiffusionLpw.from_pretrained(
        model_name_or_path,
        torch_dtype=torch_dtype,
        safety_checker=None,
        **pipe_kwargs
    )

    pipe = pipe.to(device_name)
    pipe.enable_attention_slicing()

    pipe_kwargs['pretrained_model_name_or_path'] = model_name_or_path
    pipe_kwargs['torch_dtype'] = 'torch.float16' if torch_dtype == torch.float16 else 'torch.float32'
    pipe_kwargs['scheduler'] = str(type(pipe.scheduler).__name__)

    return pipe, pipe_kwargs


def read_text_file(filename: str) -> Union[str, None]:
    path = Path(filename)
    if not Path(filename).is_file():
        return None

    content = path.read_text(encoding='utf8').strip()
    if len(content) == 0:
        return None

    return content


def load_json_dict(filename: str) -> Union[None, Dict[str, Any]]:
    result = read_text_file(filename)
    if result is not None:
        return json.loads(result)
    else:
        return None


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("diffusers_mastodon_bot.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    access_token = read_text_file('./config/access_token.txt')
    endpoint_url = read_text_file('./config/endpoint_url.txt')

    if access_token is None:
        print('mastodon access token is required but not found. check ./config/access_token.txt')
        exit()

    if access_token is None:
        print('mastodon endpoint url is required but not found. check ./config/endpoint_url.txt')
        exit()

    toot_listen_start = read_text_file('./config/toot_listen_start.txt')
    toot_listen_end = read_text_file('./config/toot_listen_end.txt')
    toot_listen_start_cw = read_text_file('./config/toot_listen_start_cw.txt')
    default_bot_name = read_text_file('./config/default_bot_name.txt')

    pipe_kwargs = load_json_dict('./config/pipe_kwargs.json')
    proc_kwargs = load_json_dict('./config/proc_kwargs.json')
    app_stream_listener_kwargs = load_json_dict('./config/app_stream_listener_kwargs.json')
    if app_stream_listener_kwargs is None:
        app_stream_listener_kwargs = {}

    diffusion_game_messages = load_json_dict('./config/diffusion_game_messages.json')

    logging.info('starting')
    mastodon = Mastodon(
        access_token=access_token,
        api_base_url=endpoint_url
    )

    logging.info('info checking')
    account = mastodon.account_verify_credentials()
    my_url = account['url']
    my_acct = account['acct']
    logging.info(f'you are, acct: {my_acct} / url: {my_url}')

    logging.info('loading model')
    device_name = 'cuda'

    pipe, pipe_kwargs = create_diffusers_pipeline(device_name, pipe_kwargs)

    logging.info('creating handlers')

    req_handlers: List[BotRequestHandler] = [
        DiffuseMeHandler(
            pipe=pipe,
            tag_name="그려줘",
        ),
        DiffuseItHandler(
            pipe=pipe,
            tag_name='베껴줘'
        ),
        DiffuseGameHandler(
            pipe=pipe,
            tag_name='그림게임',
            messages=diffusion_game_messages,  # type: ignore
            response_duration_sec=60 * 30
        )
    ]  # type: ignore

    logging.info('creating listener')
    listener = AppStreamListener(mastodon, pipe,
                                 mention_to_url=my_url,
                                 req_handlers=req_handlers,
                                 toot_listen_start=toot_listen_start,
                                 toot_listen_start_cw=toot_listen_start_cw,
                                 toot_listen_end=toot_listen_end,
                                 default_bot_name=default_bot_name,
                                 device=device_name,
                                 proc_kwargs=proc_kwargs,
                                 pipe_kwargs=pipe_kwargs,
                                 **app_stream_listener_kwargs
                                 )

    mastodon.stream_user(listener, run_async=False, timeout=10000)


if __name__ == '__main__':
    main()
