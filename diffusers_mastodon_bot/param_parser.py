import logging
import re

import unicodedata
from typing import *

from omegaconf import OmegaConf

from diffusers_mastodon_bot.conf.app.image_gen_conf import ImageGenConf
from diffusers_mastodon_bot.conf.diffusion.process_conf import ProcessConf
from diffusers_mastodon_bot.conf.diffusion.prompt_args_conf import PromptArgsConf
from diffusers_mastodon_bot.conf.diffusion.prompt_conf import PromptConf
from diffusers_mastodon_bot.utils import rip_out_html


logger = logging.getLogger(__name__)


class ParamParser:
    def __init__(
            self,
            image_gen_conf: ImageGenConf,
            prompt_conf: PromptConf,
            prompt_args_conf: PromptArgsConf,
            proc_conf: ProcessConf
    ):
        self.image_gen_conf = image_gen_conf
        self.prompt_conf = prompt_conf
        self.prompt_args_conf = prompt_args_conf
        self.proc_kwargs = OmegaConf.to_container(proc_conf)
        self.strippers = [
            re.compile(r'@[a-zA-Z0-9._-]+'),
            re.compile(r'#\w+'),
            re.compile(r'[ \r\n\t]+'),
        ]

    def process_common_params(self, html_content: str):
        prompt_conf = self.prompt_conf
        proc_kwargs = self.proc_kwargs.clone()

        content_txt = self.extract_and_normalize(html_content)

        proc_kwargs = proc_kwargs if proc_kwargs is not None else {}
        proc_kwargs = proc_kwargs.copy()
        if 'width' not in proc_kwargs:
            proc_kwargs['width'] = 512
        if 'height' not in proc_kwargs:
            proc_kwargs['height'] = 512

        content_txt, content_txt_negative, content_txt_negative_with_default, target_image_count = self.parse_args(
            content_txt, proc_kwargs
        )

        logger.info(f'text (after argparse) : {content_txt}')
        logger.info(f'text negative (after argparse) : {content_txt_negative}')

        prompts = {
            "positive": content_txt,
            "negative": content_txt_negative,
            "negative_with_default": content_txt_negative_with_default
        }

        return prompts, proc_kwargs, target_image_count

    def parse_args(self, content_txt, proc_kwargs: Dict[str, Any]):
        # param parsing
        tokens = [tok.strip() for tok in content_txt.split(' ')]
        before_args_name = None

        new_content_txt = ''

        target_image_count = self.image_gen_conf.image_count
        ignore_default_negative_prompt = False
        for tok in tokens:
            if tok.startswith('args.'):
                args_name = tok[5:]

                if args_name == 'ignore_default_negative_prompt':
                    if self.prompt_args_conf.allow_ignore_default_negative_prompt:
                        ignore_default_negative_prompt = True
                else:
                    before_args_name = args_name
                continue

            if before_args_name is not None:
                args_value = tok

                if before_args_name == 'orientation':
                    if (
                            args_value == 'landscape' and proc_kwargs['width'] < proc_kwargs['height']
                            or args_value == 'portrait' and proc_kwargs['width'] > proc_kwargs['height']
                    ):
                        width_backup = proc_kwargs['width']
                        proc_kwargs['width'] = proc_kwargs['height']
                        proc_kwargs['height'] = width_backup
                    if args_value == 'square':
                        proc_kwargs['width'] = min(proc_kwargs['width'], proc_kwargs['height'])
                        proc_kwargs['height'] = min(proc_kwargs['width'], proc_kwargs['height'])

                elif before_args_name == 'image_count':
                    if 1 <= int(args_value) <= self.image_gen_conf.max_image_count:
                        target_image_count = int(args_value)

                elif before_args_name in ['num_inference_steps']:
                    proc_kwargs[before_args_name] = min(int(args_value), 100)

                elif before_args_name in ['guidance_scale']:
                    proc_kwargs[before_args_name] = min(float(args_value), 100.0)

                elif before_args_name in ['strength']:
                    actual_value = None
                    if args_value.strip() == 'low':
                        actual_value = 0.35
                    elif args_value.strip() == 'medium':
                        actual_value = 0.65
                    elif args_value.strip() == 'high':
                        actual_value = 0.8
                    else:
                        actual_value = max(min(float(args_value), 1.0), 0.0)
                    proc_kwargs[before_args_name] = actual_value

                before_args_name = None
                continue

            new_content_txt += ' ' + tok

        if target_image_count > self.image_gen_conf.max_image_count:
            target_image_count = self.image_gen_conf.max_image_count

        content_txt = new_content_txt.strip()
        content_txt_negative = None

        if 'sep.negative' in content_txt:
            content_txt_split = content_txt.split('sep.negative')
            content_txt = content_txt_split[0]
            content_txt_negative = ' '.join(content_txt_split[1:]).strip() if len(content_txt_split) >= 2 else None

        content_txt_negative_with_default = content_txt_negative

        if self.prompt_conf.default_negative_prompt is not None and not ignore_default_negative_prompt:
            content_txt_negative_with_default = (
                content_txt_negative
                if content_txt_negative is not None
                else '' + ' ' + self.prompt_conf.default_negative_prompt
            ).strip()

        return content_txt, content_txt_negative, content_txt_negative_with_default, target_image_count

    def extract_and_normalize(self, html_content):
        logger.info(f'html : {html_content}')
        content_txt = rip_out_html(html_content)
        logger.info(f'text : {content_txt}')
        for stripper in self.strippers:
            content_txt = stripper.sub(' ', content_txt).strip()
        content_txt = unicodedata.normalize('NFC', content_txt)
        logger.info(f'text (strip out) : {content_txt}')
        return content_txt
