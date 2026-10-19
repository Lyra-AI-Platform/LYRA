# Turning on Reddit for Lyra Watch

Reddit's robots.txt disallows all crawling and its Data API terms need Reddit's approval for
commercial use, so Lyra Watch only reads Reddit through the official API with approved credentials.
Until they're set, Reddit is off and everything else works as normal.

1. Sign in to Reddit with the account that will own the app, open https://www.reddit.com/wiki/api
   and follow its link to request Data API access for commercial use. Describe Lyra Watch: counts
   and links to public threads that mention public figures; no usernames or comment text are stored
   or shown. Commercial access may carry a fee.
2. Once approved, create a "script" app at https://www.reddit.com/prefs/apps and note its client id
   and secret.
3. On the NAS, add them to the lyra service environment (for example a drop-in at
   /etc/systemd/system/lyra.service.d/reddit.conf):

       [Service]
       Environment=REDDIT_CLIENT_ID=...
       Environment=REDDIT_CLIENT_SECRET=...
       Environment="REDDIT_USER_AGENT=web:lyraauth.com:watch:v1 (by /u/<your reddit username>)"

   then `sudo systemctl daemon-reload && sudo systemctl restart lyra`.
4. Check https://lyraauth.com/api/watch/health: `sources.reddit` turns to "on". Reddit threads then
   appear under "Being discussed" and in the live feed's Discussion filter.
