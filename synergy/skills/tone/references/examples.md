# Writing Examples

These are real examples of correspondence, and the ground truth for tone, structure and voice. Each one covers a different register, so match the one closest to the message in hand rather than the last one read.

1. **Golden Reference Examples** are polished writing produced without dictation or editing. They are the target output. If an edited message does not feel like it belongs here, it has been edited too far from the voice.
2. **Standard Examples** show the typical shape of the user's correspondence in status notes, options and client emails.

The patterns to take from them are listed in the Mode B Playbook in `SKILL.md`.

---

# Section 1: Golden Reference Examples

## G1: Chat reply, technical pushback with risk framing and a safer alternative

Hey
Toby van Mook,

I think this is a much bigger question overall

My understanding is that John wants an agent that understands these types of failures and how to fix them. The agent should be able to explore all VP tools and MCP servers it has access to, decide if the tools exist or not. If not, create the tools in the VP backend and create a PR.

IMO this is very risky, and can quickly get into a place where agents have too many tools, the permissions on said tools might not be strict enough. It's also not a simple system to implement.

What would be safer to me would be to build out a toolset to get the repo, branch, file, etc. from the user script that failed. Give the agent the ability to review the code and the logs, find the probable cause, fix it, and create a PR.

But even in this case, the agent would not be able to run and test the code, as there are env vars and secrets that get passed into the container where the user script runs. We'd have to create an isolated environment where the agent would be able to test and run the code against production data without sending out to clients.

---

## G2: One-line inline observation, hedged

I think the execution ID is stored on the story. If that's the case, the meta data tables in MSSQL (which are pulled into SF via ETLs) will be able to link between the user script ID or the user script execution ID and the git info

---

## G3: Proposing an implementation as concrete bullets with code references

What about:

* Set true in `VantagePointAgentAssistant.ProcessThreadAsync` before triggering or resuming the invocation. Same pattern the other assistants follow at the top of their `ProcessThreadAsync`.
* Set false in `AgentInvocationGrain.RunInvocationProcess` in the `CompletedAgentInvocationResult` case, right after `EnsureChatBotReplyDelivered`, gated on `InvokedByChatBotId.HasValue`. The grain already has the thread identifier at that point, so it can resolve the `IChatBotThreadGrain` and call `UpdateThreadBusyGeneratingResponseAsync(false)` directly.

---

## G4: Rejecting a proposal, cause and effect one sentence at a time

`SendPendingMessagesToUserAsync` isn't the right place for it.

It does get called for agent chatbots already. `EnsureChatBotReplyDelivered` calls `SendChatBotAssistantMessageOnThreadAsync`, which calls it directly.

The problem is that setting busy=false there would fire `ChatBotThreadResponseCompleted`. That triggers another call to `SendPendingMessagesToUserAsync`, so you'd get a double send.

It also couples the busy flag to message delivery rather than invocation completion. That's not what we want the flag to mean.

---

# Section 2: Standard Examples

## S1: Two options, leaning one way

We have two options for handling this:
We can add a blanket filter for BWW on the Mayer side, so that any time BWW creates new items with a new prefix, they're automatically excluded from Mayer reporting. The risk with this is if Mayer ever needs to see BWW data in future, we'd have to remove that filter manually.
Or, we can update the BWW scripts to send only the subset of data that Mayer actually needs. This is more work but is cleaner long term.
I'd lean toward the second approach, but let me know what you think.

---

## S2: Brief technical fix note

I've pushed a fix for the null reference in the Snapshot Builder. The issue was that the new category field wasn't being initialized for tenants that hadn't gone through the migration yet. I've added a null check and a fallback to the default category.
Deployed to staging, will monitor before pushing to prod tomorrow.

---

## S3: Progress tracking with story references

Progress so far:
User Story 22104, DataFeed conversion for Forgotten Foods: ~70% complete, blocked on Snowflake connection update
User Story 22105, Mayer template alignment: complete, in review
User Story 22106, AI missing data check: not started, waiting on prioritization input
I'll continue with 22104 tomorrow once the Snowflake side is sorted.

---

## S4: Short client-facing cost estimate (email)

Hi John,
Changing the UK DB to run on S4 for a couple extra hours a week (+-8), you are looking at around $20-30 extra per month.
Thanks,
Adrienne

---

## S5: Update with timeline, estimate and the main risk (email)

Hi John,
I am hoping to have a first version ready to release before I go on leave next Thursday, even if that first version only includes the Snapshot Viewer. That does, of course, depend on how much time I get to work on it over the next two weeks.
The part that may take longer is getting everything through the App Stores, as that depends on how quickly the registration and documentation are accepted. Even if the app itself is ready before I go on leave, I will hand that process over to either Anthony or Justin so that it can continue moving while I am away.
As for adding new screens later on, that should be relatively straightforward depending on the complexity of the screen. For something like the inventory screen we discussed, where we would need to design the UI in a way that is usable on mobile, I would estimate around 15-30 hours. Other screens should not take as long, given that they would have a simpler structure.
For future screens in general, it should be relatively fast to implement the UI and the screen itself. The bigger variable is how the VP backend is set up and how easy it is to hook into that.
Thanks,
Adrienne
