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
import traceback

import diffusers.pipelines
import torch
import transformers
from PIL.Image import Image
from torch import autocast
from transformers import CLIPTokenizer, CLIPTextModel
from transformers.modeling_outputs import BaseModelOutputWithPooling

from .bot_request_handler import BotRequestHandler
from .bot_request_context import BotRequestContext
from .proc_args_context import ProcArgsContext
from ..utils import image_grid


class DiffusionRunner:
    class Result(TypedDict):
        image_filenames: List[str]
        images_list_posted: List[Any]
        has_any_nsfw: bool
        time_took: str

    re_strip_special_token = re.compile('<\|.*?\|>')

    @staticmethod
    def tokenize_prompt(
            prompt: str,
            tokenizer: CLIPTokenizer,
            ) -> torch.Tensor:  # torch.Size([1, 77])

        text_inputs = tokenizer(
            prompt,
            padding="max_length",
            max_length=tokenizer.model_max_length,
            return_tensors="pt",
        )

        # torch.Size([1, 77])
        return text_inputs.input_ids.squeeze(0)[0:77].unsqueeze(0)

    @staticmethod
    def prompt_as_input_text(prompt: str, tokenizer: CLIPTokenizer) -> str:
        text_input_ids = DiffusionRunner.tokenize_prompt(prompt, tokenizer)
        # torch.Size([1, 77])
        text_input_ids = text_input_ids[0]
        # torch.Size([77])
        decoded_text = tokenizer.decode(text_input_ids)
        decoded_text: str = DiffusionRunner.re_strip_special_token.sub('', decoded_text).strip()
        return decoded_text

    @staticmethod
    def embed_tokens(tokens: torch.Tensor, text_encoder: CLIPTextModel) -> torch.Tensor:
        # https://github.com/huggingface/diffusers/blob/v0.4.2/src/diffusers/pipelines/stable_diffusion/pipeline_stable_diffusion.py
        # torch.Size([1, 77])
        embedding: BaseModelOutputWithPooling = text_encoder(tokens.to(text_encoder.device))
        # torch.Size([1, 77, 768])
        return embedding.last_hidden_state

    @staticmethod
    def embed_prompt(prompt: str, tokenizer: CLIPTokenizer, text_encoder: CLIPTextModel):
        tokenized = DiffusionRunner.tokenize_prompt(prompt, tokenizer)
        # torch.Size([1, 77])
        embed = DiffusionRunner.embed_tokens(tokenized, text_encoder)
        # torch.Size([1, 77, 768])

        return embed

    @staticmethod
    def make_processing_body(
            pipe: diffusers.pipelines.StableDiffusionPipeline,
            args_ctx: ProcArgsContext
    ) -> str:
        # start message
        processing_body = ''

        # noinspection PyUnresolvedReferences
        tokenizer: transformers.CLIPTokenizer = pipe.tokenizer  # type: ignore

        positive_input_form = DiffusionRunner.prompt_as_input_text(args_ctx.prompts['positive'], tokenizer)

        if positive_input_form != args_ctx.prompts["positive"]:
            processing_body += f'\n\npositive prompt:\n{positive_input_form}'

        if args_ctx.prompts['negative'] is not None and len(args_ctx.prompts['negative']) > 0:
            negative_input_form = DiffusionRunner.prompt_as_input_text(args_ctx.prompts['negative'], tokenizer)
            if negative_input_form != args_ctx.prompts["negative"]:
                processing_body += f'\n\nnegative prompt:\n{negative_input_form}'

        return processing_body[0:400]

    @staticmethod
    def run_diffusion_and_upload(pipe: diffusers.pipelines.StableDiffusionPipeline,
                                 ctx: BotRequestContext,
                                 args_ctx: ProcArgsContext) -> Optional[Result]:
        result: DiffusionRunner.Result = {
            "image_filenames": [],
            "images_list_posted": [],
            "has_any_nsfw": False,
            "time_took": ''
        }

        generated_images_raw_pil = []

        with autocast(ctx.bot_ctx.device_name):
            start_time = time.time()
            filename_root = datetime.now().strftime('%Y-%m-%d') + f'_{str(start_time)}'

            left_images_count = args_ctx.target_image_count

            while left_images_count > 0:
                cur_process_count = min(ctx.bot_ctx.max_batch_process, left_images_count)
                logging.info(
                    f"processing {args_ctx.target_image_count - left_images_count + 1} of {args_ctx.target_image_count}, "
                    + f"by {cur_process_count}")

                pipe_results = pipe(
                    [args_ctx.prompts['positive']] * cur_process_count,
                    negative_prompt=([args_ctx.prompts['negative_with_default']] * cur_process_count
                                     if args_ctx.prompts['negative_with_default'] is not None
                                     else None),
                    **args_ctx.proc_kwargs
                )

                generated_images_raw_pil.extend(pipe_results.images)
                if pipe_results.nsfw_content_detected:
                    result["has_any_nsfw"] = True

                left_images_count -= ctx.bot_ctx.max_batch_process

            end_time = time.time()

            time_took = end_time - start_time
            time_took = int(time_took * 1000) / 1000

            result["time_took"] = f'{time_took}s'

            # save anyway
            for idx in range(args_ctx.target_image_count):
                image_filename = str(Path(ctx.bot_ctx.output_save_path, filename_root + f'_{idx}' + '.png').resolve())
                text_filename = str(Path(ctx.bot_ctx.output_save_path, filename_root + f'_{idx}' + '.txt').resolve())

                time_took += end_time - start_time

                image: Image = generated_images_raw_pil[idx]

                image.save(image_filename, "PNG")
                Path(text_filename).write_text(json.dumps(args_ctx.prompts))

                result["image_filenames"].append(image_filename)

        logging.info(f'preparing images to upload')

        image_grid_unit = int(ctx.bot_ctx.image_tile_xy[0] * ctx.bot_ctx.image_tile_xy[1])
        pil_image_grids = []
        if args_ctx.target_image_count == 1:
            pil_image_grids = generated_images_raw_pil
        else:
            for i in range(0, len(generated_images_raw_pil), image_grid_unit):
                cur_pil_image_slice = generated_images_raw_pil[i: i + image_grid_unit]

                image_slice_len = len(cur_pil_image_slice)

                max_x = ctx.bot_ctx.image_tile_xy[0] \
                    if image_slice_len >= ctx.bot_ctx.image_tile_xy[0] \
                    else ctx.bot_ctx.image_tile_xy[0] % len(cur_pil_image_slice)
                max_y = math.ceil(image_slice_len / ctx.bot_ctx.image_tile_xy[0])

                fitting_square = math.pow(math.floor(math.sqrt(image_grid_unit)), 2)

                if fitting_square > max_x * max_y:
                    max_x = fitting_square
                    max_y = max_y

                grid_image = image_grid(cur_pil_image_slice, max_x, max_y)
                pil_image_grids.append(grid_image)

        logging.info(f'uploading {len(generated_images_raw_pil)} images')

        for pil_image in pil_image_grids:
            try:
                # pil to png
                # https://stackoverflow.com/a/33117447/4394750
                img_byte_arr = io.BytesIO()
                pil_image.save(img_byte_arr, format='PNG')
                png_bytes = img_byte_arr.getvalue()

                upload_result = ctx.mastodon.media_post(png_bytes, 'image/png')
                result["images_list_posted"].append(upload_result)
            except Exception as ex:
                logging.error(f'error on image upload:\n' + "\n  ".join(traceback.format_exception(ex)))
                pass

        return result
