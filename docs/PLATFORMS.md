# Platform research

How the platforms were chosen, how each integration works, and which platforms were researched but rejected.

## Selection criteria

1. **Self-serve API access.** A free token can be created in minutes, with no app review or paid tier.
2. **A public URL for the post**, so `posted_url` and `public_access` mean something.
3. **Plain text with a link is allowed** and the text limit is at least 200 characters, so the message never has to be cut.
4. **Official, documented REST API**, called directly with HTTPX (no vendor SDKs).

## Integrated platforms

| Platform | Endpoint | Auth | `posted_url` comes from | Public? | Limits and notes |
|---|---|---|---|---|---|
| **Telegram** | `POST https://api.telegram.org/bot<token>/sendMessage` | Bot token in the URL path (from @BotFather). The bot must be an admin of the channel | `https://t.me/<channel_username>/<message_id>` | Yes, for a channel with a public username. Private channels give a `t.me/c/...` link and `public_access: false` | 4096 chars. About 20 messages per minute per channel. The token appears in the URL, so httpx request logging is turned off |
| **Mastodon** | `POST {instance}/api/v1/statuses` | `Authorization: Bearer <token>`, scope `write:statuses` | Response field `url` | Yes (`visibility: public`) | 500 chars on mastodon.social. Sends an `Idempotency-Key` header, so retries can't double-post |
| **Bluesky** | `com.atproto.server.createSession`, then `com.atproto.repo.createRecord` | Handle and **app password** → access JWT | `https://bsky.app/profile/<handle>/post/<rkey>` (rkey is the last part of the returned `at://` URI) | Yes | 300 graphemes. Links are only clickable with a **link facet**, whose offsets are **UTF-8 byte** positions (not character positions). The session is cached for 30 min because `createSession` is rate-limited (30 per 5 min) |
| **GitHub Gist** | `POST https://api.github.com/gists` | `Authorization: Bearer <PAT>`: classic PAT with `gist` scope, or fine-grained PAT with *Gists: read and write* | Response field `html_url` | Yes (`public: true`) | Creating content is limited to about 80 requests per minute. The message is stored as `post.md` |
| **Telegraph** | `POST https://api.telegra.ph/createPage` | `access_token` from a one-off `createAccount` call (`scripts/telegraph_account.py`) | Response `result.url` | Yes, every page is public | Needs a `title` (taken from the message). Content is a Node array, with the link as an `<a>` node. **Errors come back as HTTP 200 with `ok: false`**, so the adapter checks `ok` |
| **Dev.to** (Forem) | `POST https://dev.to/api/articles` | `api-key: <key>` header, `Accept: application/vnd.forem.api-v1+json` | Response field `url` | Yes (`published: true`) | Needs a title (taken from the message). At most 4 tags. Forem rejects posting the same body twice. New accounts may be rate-limited or held for moderation |
| **Hugging Face** (LLM platform) | `POST https://huggingface.co/api/{repo_type}s/{repo_id}/discussions` | `Authorization: Bearer <write token>` | `https://huggingface.co/[spaces/\|datasets/]<repo_id>/discussions/<num>` | Yes, when the repo is public | Opens a discussion on **our own** public repo, never on someone else's. Same endpoint that `huggingface_hub.HfApi.create_discussion` uses |
| **Discord** | `POST <webhook_url>?wait=true` | The webhook URL itself is the secret | `https://discord.com/channels/<guild_id>/<channel_id>/<message_id>` | Only if the server is public (`DISCORD_SERVER_PUBLIC`), otherwise `public_access: false` | 2000 chars. `wait=true` makes Discord return the message. `allowed_mentions.parse = []` stops `@everyone` pings |

### Official documentation

- Telegram: https://core.telegram.org/bots/api#sendmessage
- Mastodon: https://docs.joinmastodon.org/methods/statuses/#create
- Bluesky: https://docs.bsky.app/docs/api/com-atproto-repo-create-record and https://docs.bsky.app/docs/advanced-guides/post-richtext
- GitHub Gist: https://docs.github.com/en/rest/gists/gists#create-a-gist
- Telegraph: https://telegra.ph/api#createPage
- Dev.to / Forem: https://developers.forem.com/api/v1#tag/articles/operation/createArticle
- Hugging Face: https://huggingface.co/docs/hub/en/repositories-pull-requests-discussions
- Discord: https://discord.com/developers/docs/resources/webhook#execute-webhook

## Why Hugging Face counts as the "LLM platform"

The brief asks for "third-party websites, portals, and supported LLM platforms". LLM chat products (ChatGPT, Claude, Gemini) have no API for publishing public content. The closest real match is a platform where the AI/LLM community publishes, and that has a public write API. Hugging Face Hub is the main home of open LLMs. Its discussions are public, have stable URLs, and can be created through a documented endpoint with a personal token.

## Researched and rejected

| Platform | Why not |
|---|---|
| X / Twitter | Write access requires a paid API tier (the free tier is very limited) and OAuth 1.0a user context |
| LinkedIn | 3-legged OAuth, plus approval for the "Share on LinkedIn" product; tokens expire after 60 days |
| Facebook / Instagram / Threads | Meta app review, and a Page or Business account is required |
| Reddit | API access now needs approval; posts from new accounts are routinely spam-filtered |
| Medium | The API is deprecated and no new integration tokens are issued |

None of these have stub adapters. An adapter that can never be configured would show up as a permanent failure in every response.
