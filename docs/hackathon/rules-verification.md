# Rules verification

Each question: answer + source + date. "Ask" means the official rules and FAQ do not
settle it; the drafted question is ready to send to the organizers.

1. **Is the submission editable after the deadline?**
   Answered: no. The hackathon update "Final stretch" (checked 2026-10-21): "Once the
   deadline passes, submissions are locked. Please do not edit your code repo, video,
   or any project materials from the deadline until after the winner announcement."
   Nothing changes from 23 Oct 12:00 PT to 3 Dec; see `decisions.md` (D-AMZ-22).

2. **How does a self-hosted MCP server connect to Alexa+, and how do judges
   test it?**
   Answered: it doesn't. Those developer tools are partner-only, and the organizers
   confirmed on the forum that hackathon participants cannot get access. The FAQ says a
   web page that acts as an actual MCP client (initialize, tools/list, tools/call over
   Streamable HTTP) satisfies the simulated-experience path; the device does exactly
   that. See `decisions.md` (D2, D-AMZ-23).

3. **Where exactly are Product Feedback and Friction Logs submitted?**
   Ask. The rules require the feedback; the form fields are only visible when
   submitting. Draft: "Is Product Feedback a form field, a repository file or a
   link?" Until answered: paste it in the form and keep `amazon-feedback.md` and
   `amazon-friction-log.md` in the repository.

4. **Does the repo URL accept a tag/release URL instead of the default
   branch?**
   Ask. Draft: "May the repository field point to a release or tag URL?" Until
   answered: use the default branch and tag `amazon-v1.0` on the same commit.

5. **Does this track require a live demo/endpoint during judging?**
   Answered: yes. The FAQ said a locally runnable repo is enough, but a later organizer
   answer on the forum (checked 2026-10-21) says the MCP server "needs to be live and
   accessible till the end of the judging period" (20 Nov). Another answer: replay mode
   by default is fine, but a judge must not be required to paste in their own token.
   See `decisions.md` (D-AMZ-21).

6. **If the repo stays private, does `testing@devpost.com` have a GitHub
   username to invite?**
   Moot: the repository and the library have been public, with an MIT license
   detected at the top, since 20 Oct.
