<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Worked examples

Five replies written to the standard in `SKILL.md`: a finished run, a
partially finished run, work that needs a person to complete it, a
blocked run, and a recommendation. Each one is followed by what was
deliberately left out.

Read these when you are unsure how much to cut, or when a report is
turning into a list of everything you did.

---

## Example 1: Finished and deployed

> I fixed the employee list extraction and deployed the fix to
> production.
>
> The source website had changed, which stopped the extraction from
> moving between locations. The imports had been completing without
> errors the whole time, which is why the failure was not obvious. The
> fix has been validated against live data.

**Left out:** which files changed, the search that found the cause, the
two theories that turned out to be wrong, and the test names.

**Why it works:** the first sentence carries both the outcome and the
state. The second paragraph explains the cause and, importantly, why the
problem was not visible earlier. A successful run that produced no data
is not the same as a successful run.

---

## Example 2: Code done, nothing merged

> I made the code changes for issue #1091 Deploy the backend Worker and
> opened PR #1092 Make the backend Worker deployable. **The PR has not
> been merged or deployed.**
>
> ### Outstanding
>
> - Run the database updates.
> - Deploy to sandbox, then production.
> - Add the private credentials.
>
> I could not do these because I do not have permission to change the
> hosting and repository settings they need.
>
> ### Assumptions
>
> I left the existing credential in place rather than replacing it. It
> looks like the wrong type for this integration, but I do not know
> whether it was created for something else.

**Left out:** the commit list, the quality gate output, and the branch
name.

**Why it works:** the state is stated in bold because it is the thing
most likely to be misread. Both work items are named, not just
numbered. Outstanding sits near the top and says plainly why the work
stopped, without going into scopes and permission models.

---

## Example 3: Work a person has to finish

> I completed the content rating questionnaire. **Nothing has been saved
> or submitted yet.**
>
> ### Outstanding
>
> You need to review the answers and submit the rating.
>
> ### Assumptions
>
> I answered No to "Primarily news or educational" because the app is a
> reader for content the user already owns, rather than a news or
> educational product.

**Left out:** every other question and answer in the form.

**Why it works:** only the one judgement call is surfaced. The other
answers were obvious from the app, so listing them would bury the one
that a person might disagree with.

---

## Example 4: Blocked

> I could not start issue #204 Add the export scheduler. The story does
> not say what should happen when a scheduled export overlaps a running
> one, and any answer I picked would be a guess.
>
> I marked it blocked and left a comment on it asking for that decision.
> I have not written any code for it.
>
> ### Outstanding
>
> Decide whether an overlapping export should queue, be skipped, or
> cancel the running one. Once that is on the issue, the story can be
> picked up as it stands.

**Left out:** the parts of the story that were clear, and the
implementation that would have worked for two of the three answers.

**Why it works:** it says what is blocked, why, what state the work is
in (none written), and exactly what unblocks it. It does not pad the
report with the part of the problem that was easy.

---

## Example 5: A recommendation

> I would do the link scanner first. It is roughly 20 to 30 hours of
> mostly one-off work and should need very little maintenance
> afterwards.
>
> The newsjacking approach is cheaper per event, but it only works if
> pages can be published quickly, and it has to be done regularly to be
> worth anything.
>
> I have not rechecked issue #278 Fix publishing pipeline, so I am
> assuming from that issue that fast publishing is still a problem. If
> that has been fixed, the two options are much closer and I would want
> to look again.

**Left out:** a feature-by-feature comparison, and a third option that
was ruled out early.

**Why it works:** the recommendation comes first with its main reason.
The option not chosen is still described, so the decision stays with the
reader. The estimate is a range and says what it covers. The assumption
that the recommendation rests on is stated, along with what would change
if it is wrong.

---

## What all five have in common

- The first sentence is the outcome, not the background.
- The completion state is explicit, and exact about which state it is.
- Work items are named as well as numbered.
- Nothing appears twice.
- Nothing is there to prove the work was done thoroughly.
- Where a section had nothing to say, it is absent rather than empty.
