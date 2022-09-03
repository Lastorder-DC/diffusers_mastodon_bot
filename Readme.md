# duffusers_mastodon_bot

a quick and dirty bot, running stable diffuser, via huggingface diffusers

## prepare & run

- virtualenv
- install pytorch, via pip, enabling nvidia
- `pip install -r requirements.txt`
- `huggingface-cli login` (see hf diffusers)
- create app from account setting, fill these text files
  - `config/access_token.txt`
  - `config/endpoint_url.txt` ex) `https://mastodon.social
  - optional
    - `config/toot_listen_start.txt`: toot content on listening start
    - `config/toot_listen_end.txt`: toot content on listening end (exit)
- `python -m diffusers_mastodon_bot.main`

## use

mention to target acct user with tag, hardcoded are:

- user itself
- #diffuse_me

```text
@diffuse_bot@example.com #diffuse_me prompt text shown in dark monitor in parking lot
```

## misc

listening to user stream is intentional, for self-sending.