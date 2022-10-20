# duffusers_mastodon_bot

a quick and dirty bot, running stable diffuser, via huggingface diffusers

## prepare & run

- virtualenv
- install pytorch, via pip, enabling nvidia
- cuda version should match(If pytorch is based on cuda 11.6, install cuda 11.6 instead of 11.8)
- `pip install -r requirements.txt`
- `huggingface-cli login` (see hf diffusers)
- create app from account setting, fill these text files
  - `config/access_token.txt`
  - `config/endpoint_url.txt` ex) `https://mastodon.social
  - optional
    - see `config_example`
- `python -m diffusers_mastodon_bot.main`

## features

- image generation: mentioning the bot with `#diffuse_me` and prompt
  - If you are the bot, You can do it without mention
- image generation game: mentioning the bot in DM with `#diffuse_game` and prompt

```text
@bot@example.com 

#diffuse_me 

args.orientation landscape
args.image_count 16
args.guidance_scale 30
args.num_inference_steps 70

suzuran from arknights at cozy cafe with tea.
extremely cute, round face, big fox ears directing side,
cyan hairband, bright gold yellow hair with thin twintail
as round shape braided, bangs, round gentle emerald eyes,
girlish comfort dress, 1girl, urban fantasy, sci-fi,
comfort art style, ultra detail, highres

sep.negative

high contrast, trecen school suite, uma musume
```

## config examples

<<<<<<< HEAD
### `config/proc_kwargs.json`

bug?: https://github.com/huggingface/diffusers/issues/255

```json
{
  "width": 512,
  "height": 704,
  "num_inference_steps": 70,
  "guidance_scale": 12.0
}
```

### `config/app_stream_kwargs.json`

```json
{
  "image_count": 4,
  "max_image_count": 16,
  "image_tile_xy": [2, 2],
  "max_batch_process": 1,
  "delete_processing_message": false,
  "toot_on_start_end": true,
  "default_negative_prompt": "nsfw, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry"
}
```
=======
see `config_example`. copy-paste it to `config` and modify from there.
>>>>>>> 3a5eac5dbbcf954639073c0e5c39c26069858210
