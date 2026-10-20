# Rules verification

Each question: answer + source + date. "Ask" means the official rules and FAQ do not
settle it; the drafted question is ready to send to the organizers.

1. **Is the submission editable after the deadline?**
   Ask (not settled by the rules text we have, checked 2026-10-06). Draft: "Can a
   Devpost submission be edited after 23 Oct 12:00 PT, for example to fix a link or a
   video, and does an edit after the deadline disqualify it?" Until answered, assume
   it cannot be edited: submit one day early (target 22 Oct).

2. **How does a self-hosted MCP server connect to Alexa+, and how do judges
   test it?**
   Answered: it doesn't. Those developer tools are partner-only. See
   `decisions.md` (D2).

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
   Answered: no. See `decisions.md` (D-AMZ-1).

6. **If the repo stays private, does `testing@devpost.com` have a GitHub
   username to invite?**
   Ask. Moot if the repository is public at submission time, which is the cheapest
   way to close it. Otherwise invite `testing@devpost.com` and the six reviewers
   named in the rules; invitations can expire, so re-check before the deadline.
