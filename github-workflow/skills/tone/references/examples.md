<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Writing Examples

These are real examples of correspondence. Study them closely before editing any draft. They are the ground truth for tone, structure, and voice.

The file is split into two sections:

1. **Golden Reference Examples** -- polished writing produced without dictation or editing. These represent the target output. If an edited message does not feel like it belongs in this section, it has been edited too far away from the voice.
2. **Standard Examples** -- real correspondence that shows the typical range of writing across work, technical, and client-facing contexts.

---

# Section 1: Golden Reference Examples

These were written directly, fully polished, no dictation mistakes. They are the clearest picture of the natural written voice, especially for Slack, Teams, chat replies, and inline technical responses. Match this style when editing dictated or rough drafts.

**Key patterns visible in these examples:**

- Opens with a name or a short hook ("Hey", "What about:", a direct rejection like "`X` isn't the right place for it") rather than a formal greeting
- Uses "I think", "IMO", "My understanding is that", "What would be safer to me"; personal framing, not neutral reporting
- Risk and trade-off framing spelled out explicitly ("this is very risky", "can quickly get into a place where...")
- Backticks around method names, class names, file names, variable names; inline code formatting is preserved, not flattened to quotes
- Bulleted technical proposals where each bullet is a concrete action with a location (file, method, grain, line of behaviour)
- Short paragraphs, single-thought per line, spaced out vertically
- Chains of reasoning presented as sequential sentences rather than one compound sentence. Each cause and effect gets its own sentence.
- Rejections name what breaks concretely (e.g. "you'd get a double send") rather than abstractly ("which is the wrong semantic")
- No sign-off, no "Thanks", no closing line. The message ends when the content ends.
- Hedging words used deliberately ("probably", "likely", "IMO", "my understanding"); not stripped out
- Proper nouns typed correctly (no dictation near-misses to fix)

---

## Golden Example G1: Technical pushback with risk framing and a safer alternative

Hey
Toby van Mook, 

 
I think this is a much bigger question overall 
 
My understanding is that John wants an agent that understands these types of failures and how to fix them. The agent should be able to explore all VP tools and MCP servers it has access to, decide if the tools exist or not. If not, create the tools in the VP backend and create a PR. 
 
IMO this is very risky, and can quickly get into a place where agents have too many tools, the permissions on said tools might not be strict enough. It's also not a simple system to implement. 
 
What would be safer to me would be to build out a toolset to get the repo, branch, file, etc. from the user script that failed. Give the agent the ability to review the code and the logs, find the probable cause, fix it, and create a PR.
 
But even in this case, the agent would not be able to run and test the code, as there are env vars and secrets that get passed into the container where the user script runs. We'd have to create an isolated environment where the agent would be able to test and run the code against production data without sending out to clients. 

---

## Golden Example G2: Short inline technical observation linking data locations

I think the execution ID is stored on the story. If that's the case, the meta data tables in MSSQL (which are pulled into SF via ETLs) will be able to link between the user script ID or the user script execution ID and the git info 

---

## Golden Example G3: Proposing a specific implementation with code references

What about:

* Set true in `VantagePointAgentAssistant.ProcessThreadAsync` before triggering or resuming the invocation -- same pattern the other assistants follow at the top of their `ProcessThreadAsync`.
* Set false in `AgentInvocationGrain.RunInvocationProcess` in the `CompletedAgentInvocationResult` case, right after `EnsureChatBotReplyDelivered`, gated on `InvokedByChatBotId.HasValue`. The grain already has the thread identifier at that point, so it can resolve the `IChatBotThreadGrain` and call `UpdateThreadBusyGeneratingResponseAsync(false)` directly.

---

## Golden Example G4: Rejecting a proposed location with a mechanical explanation

`SendPendingMessagesToUserAsync` isn't the right place for it.

It does get called for agent chatbots already. `EnsureChatBotReplyDelivered` calls `SendChatBotAssistantMessageOnThreadAsync`, which calls it directly.

The problem is that setting busy=false there would fire `ChatBotThreadResponseCompleted`. That triggers another call to `SendPendingMessagesToUserAsync`, so you'd get a double send.

It also couples the busy flag to message delivery rather than invocation completion. That's not what we want the flag to mean.

---

# Section 2: Standard Examples

## Example 1: Multi-topic status update with estimates

Timing on Extraction Script Changes
My ballpark estimate for updating all extraction scripts across tenants is around 6-8 hours per extraction script where the script is used across most tenants, and around 2-3 hours for scripts that are only used by a few. This includes converting them to DataFeed (including only using VaultEntries for config), making the necessary Snowflake connection updates, and migrating all tenants to the correct version.
There are quite a few extraction scripts in total, so I'd estimate roughly 40-60 hours overall for full completion.
AI Checks for Missing Data
I'll start with this next. I'm just wrapping up a few small tweaks to the Snapshot Builder to better align it with the Mayer template. Once that's done later today, I'll move on to the AI checks for missing data.
Better Ways to Check for Missing Extraction Data
We can write a generic data check script that runs across all tenants and compares the number of records extracted over time. For example, it could look at each day in the past month and compare it to the current day's extraction run. We could include a 10-15% tolerance threshold so that if there's a drop beyond that, the pipeline fails and flags it for review.
Building this would take about 4-5 hours and would give us a good automated check.
Would you like me to do this work, and should it be prioritized over the AI checks? This is much faster to set up and I think will also be relatively robust. My suggestion would be to do this task first.
Extraction Scripts Not Using the System Mode Versions
I can create new repo files for any extraction scripts that are still using legacy versions. That process shouldn't take long, about 20-30 minutes per script. I'll then create System Mode variants for each, which will let us use those versions for new tenant setups without affecting any of the existing ones. That way, we're not continuing to add legacy scripts while still giving flexibility to roll out updates gradually across tenants that are already using the extraction scripts.
Altogether, I'd estimate about 12 hours to set this up.
I can also create a check script that runs daily, queries the database for any new references to the old extraction file paths, and sends an internal alert if any are found. That should take around 3 hours to write and set up.
Summary of Estimated Hours
Conversion of all extraction scripts (includes the 12 hours from the next point): 40-60 hours
Create System Mode variants of all extraction scripts (without converting existing clients): 8-12 hours
AI checks for missing data: 20 hours
Generic data validation script: 4-5 hours
Daily legacy extraction script alert setup: 3 hours

---

## Example 2: Delegating work with estimates

I spoke to Adam about which user script development Paul can be assigned to, and I think having him setup the Weekly version of the Forgotten Foods generic snapshot template would be very helpful.
Currently, we don't have any tenants that are asking to use that template, but there probably will be in the near future.
I would estimate around 16-18 hours for the full development time, which includes all designation variants of the scripts.
If you're happy with this, I can write a technical spec for Paul to follow. He'll also be able to use the SMV variant to give him an idea of what to do now that it's been completed.

---

## Example 3: Technical announcement

There has been an update to the vp_bootstrap package, that should be used moving forward - also outlined in the associated wiki article.
- The vp_bootstrap package has been updated to enable the dynamic loading of the VP Library reference scripts.
- Ensure you have the latest version of the vp_bootstrap package installed: 0.2.0
- First run the file: setup_vp_system_repo.bat
- Then the reference scripts can be accessed as:
...

---

## Example 4: Short clarification

I have advised Paul on the standard processes within user scripts, but what this script needs to do depends on how the Snowflake tables and Tasks are setup. Usually, someone on the Vantage Team sets up the Snowflake side, and we use that in a standard way within the scripts.

---

## Example 5: Raising a people issue

I wanted to bring something to your attention that feels small on the surface but ties into a larger pattern I've been noticing.
Rachel was running into issues testing reference scripts on Vantage Point, so I had a call with her earlier this week to talk her through what to do. She said she understood and gave it a shot, but later came back asking if I could look at her code.
Instead of outright giving her the answer, I asked her to outline what documentation she'd read, what she tried, and where things were breaking, just to encourage a bit more ownership in troubleshooting. I also asked her to move our conversation into the VP Team Sharing chat so the whole team could benefit. I made that request twice, and she acknowledged it with a thumbs up.
Note: I initially asked her to "in future" ask questions like this in the VP Team Sharing chat, but on subsequent requests I explicitly asked her to move our current chat to the group, as I thought it would be valuable for the whole team to understand how to test reference scripts on VP.
When she had not posted anything by the next day, and made no mention of planning to, I followed up and asked when she planned to share. She seemed confused about why it needed to go in the team chat, so I explained again that this is exactly the kind of thing the whole VP team should understand.
In my last message, I quoted all the times I had explicitly asked her to move the conversation to the group chat and made it clear that I was asking her to summarize her issue and the solution on the team chat so that everyone can understand how to do this in future. That message has gone unanswered, and there's still nothing posted in the team chat. At this point, I've asked four times, and there's been no response or follow-through.
To be honest, I'm feeling a bit stuck. I've seen similar behavior from others on the team, when I ask things like how a PR was accidentally merged or request a rundown of debugging steps, it often gets ignored or left unanswered.
I know these things may not seem urgent on their own, but they do point to a deeper cultural issue around initiative and follow-through that I think is worth looking at.

---

## Example 6: Proposing a tool/process improvement

Automated PR Reviews With AI
There are a number of free extensions we can use (or develop our own) which automatically runs AI Analysis using our coding standards against the code, and creates comments in-line. All we would need is an Azure OpenAI API Key.
Thus far, the best one I have found is: AI-Powered PR Comments created by Byte Insights
Python PR Template
On the Python side of things, I think that we can update the template to be more concise (as there is a character limit), and include additional sections. In addition, I don't think we need to link to the wiki sections, as a majority of the team have already been through all the wikis, or they don't use the link anyway.
Proposed update to the Python PR Template:
...

---

## Example 7: Short status update with attachment

I have a version of the report prepared and attached. It details which user scripts are using which deprecated functions, methods, and packages.
We've also identified potential solutions to avoid having to update every user script, as it appears that most are relying on one of the deprecated functions. I'll provide further feedback on possible bulk updates after I've discussed further with the Inversion team.

---

## Example 8: Incident report / root cause analysis

There were two primary issues encountered with the PJN scripts between July 1st and July 2nd:
- Some emails not being sent
	- Around the time the email issues occurred on the 1st and 2nd, we observed a significant number of Orleans logs indicating dropped expired messages, as well as some service bus messages being dead-lettered. As such, it seems like the website was experiencing high request volumes and elevated resource usage. Based on this, it appears the root cause was general system strain due to unusually high load during that period.
- Duplicate emails being sent to some users
	- We observed HTTP timeouts during attempts to queue batches of emails, likely caused by the email manager component being under load and unable to accept new requests quickly enough. This component isn't expected to block during normal email queuing, so the delays were probably due to slower operations within it, such as cache access or calls to blob storage to retrieve email metadata like blob sizes. Our working theory is that although the original calls timed out, the messages were eventually processed. However, because the Service Bus retried those messages, the same emails were re-queued and sent again, leading to duplicates.
	- To address this, we're proposing a change that introduces a unique identifier for each email at the point of creation from the Python-based user script runners. This would allow downstream systems to recognize and ignore duplicate messages if retries occur, effectively eliminating the risk of sending the same email multiple times due to infrastructure-level retries. This fix is covered by: User Story 21869: User Scripts - add a unique ID to email messages from Python

---

## Example 9: Internal process update

I have updated the Vantage Internal Wiki to install Python 3.12 instead of Python 3.9.13.
I will send out an internal process release email later today or tomorrow, but I wanted to let you know in advance that, ideally, before the release on Staging goes out, that the Vantage Team start upgrading/recreating their local environments.
Wiki can be found here: Python Virtual Environments & IDE Standardisation

---

## Example 10: Suggesting a direction with caveats

We have two options for handling this:
We can add a blanket filter for BWW on the Mayer side, so that any time BWW creates new items with a new prefix, they're automatically excluded from Mayer reporting. The risk with this is if Mayer ever needs to see BWW data in future, we'd have to remove that filter manually.
Or, we can update the BWW scripts to send only the subset of data that Mayer actually needs. This is more work but is cleaner long term.
I'd lean toward the second approach, but let me know what you think.

---

## Example 11: Raising a process concern

I wanted to flag something that has been bothering me for a while.
A lot of the Vantage Team's time is spent fixing issues on user scripts that could have been caught earlier. We don't have a consistent testing process for user script changes, and PRs often go in without anyone running them end-to-end against realistic data.
I think we'd benefit from formalizing a lightweight test process before merge, something like: run the script against a known test tenant, check that the outputs match what's expected, and attach the results to the PR. It doesn't need to be automated, just documented.
This would take a bit more time upfront per PR but would save us a lot of post-deploy firefighting.
Let me know if you want me to draft something concrete.

---

## Example 12: Quick issue resolution note

The issue with the Mayer extraction was that the Snowflake connection was pointing at the old database name. I've updated the config and re-run the pipeline, and it's now pulling the correct data.

---

## Example 13: Brief technical fix note

I've pushed a fix for the null reference in the Snapshot Builder. The issue was that the new category field wasn't being initialized for tenants that hadn't gone through the migration yet. I've added a null check and a fallback to the default category.
Deployed to staging, will monitor before pushing to prod tomorrow.

---

## Example 14: Progress tracking with story references

Progress so far:
User Story 22104, DataFeed conversion for Forgotten Foods: ~70% complete, blocked on Snowflake connection update
User Story 22105, Mayer template alignment: complete, in review
User Story 22106, AI missing data check: not started, waiting on prioritization input
I'll continue with 22104 tomorrow once the Snowflake side is sorted.

---

## Example 15: Asking for prioritization input

There are a few pieces of work competing for time this week:
- Mayer extraction fix (urgent, client-facing)
- Agent Framework tool sets (important but not urgent)
- Snapshot Builder updates (planned work, can shift)
I'll default to the Mayer fix first, but want to check if there's anything on the other two that needs to move this week.

---

## Example 16: Comprehensive status update with next steps question

Hi John,
Here's where things stand on the Agent Framework:
Tool Sets Built
- User Script Investigation: complete and tested against a few failure scenarios
- Pipeline Investigation: complete, tested end-to-end
- Source/Code Investigation: in progress, about 60% done
- Azure DevOps integration via LiteLLM: complete but needs auth review
Next Steps
I'd like to prioritize finishing the Source/Code Investigation tool set this week, then move on to documenting how the agents get assembled with different tool combinations per use case.
Would you prefer I focus on the documentation next, or start on the QSR-specific use cases?

---

## Example 17: Correcting a misunderstanding diplomatically

Just to clarify on yesterday's call, the change I proposed wasn't to remove the existing validation, but to add a layer on top of it. The existing validation stays as-is. The new layer just catches cases where the existing validation passes but the data is still semantically wrong (e.g. correct format but impossible values).
Happy to walk through it again if that's useful.

---

## Example 18: Short proposal with question

I'd like to consolidate the three check scripts we have into a single configurable one. They're doing very similar things and maintaining three versions has caused drift. Estimate is around 6 hours.
OK to proceed?

---

## Example 19: Follow-up and delegation

Following up on the Mayer extraction, I've handed the day-to-day monitoring over to Toby so I can focus on the Agent Framework work. Toby has the context on the recent fix and will flag anything that needs escalation.

---

## Example 20: Short client-facing cost estimate (email)

Hi John,
Changing the UK DB to run on S4 for a couple extra hours a week (+-8), you are looking at around $20-30 extra per month.
Thanks,
Adrienne

---

## Example 21: Mobile app update with timeline and estimate (email)

Hi John,
I am hoping to have a first version ready to release before I go on leave next Thursday, even if that first version only includes the Snapshot Viewer. That does, of course, depend on how much time I get to work on it over the next two weeks.
The part that may take longer is getting everything through the App Stores, as that depends on how quickly the registration and documentation are accepted. Even if the app itself is ready before I go on leave, I will hand that process over to either Anthony or Justin so that it can continue moving while I am away.
As for adding new screens later on, that should be relatively straightforward depending on the complexity of the screen. For something like the inventory screen we discussed, where we would need to design the UI in a way that is usable on mobile, I would estimate around 15-30 hours. Other screens should not take as long, given that they would have a simpler structure.
For future screens in general, it should be relatively fast to implement the UI and the screen itself. The bigger variable is how the VP backend is set up and how easy it is to hook into that.
Thanks,
Adrienne

---

## Example 22: Proposing a technical approach with multiple options (email)

Hi John,
Thanks. That helps to clarify.
I will try with pure OCR, but it's also worth investigating adding in an LLM layer to structure the data into the format that you require. I've worked on a couple other projects with this combination of Azure OCR and LLM processing, which gives 100% reliable output.
I'll try with both approaches and get back to you.
Thanks,
Adrienne

---

## Example 23: Short internal update confirming changes made (email)

Hi Tracy,

I've updated the category list with the additional categories that you requested.

I also added both the client's name and category fields to epics and features.

Let me know if you need any other changes.

Thanks,
Adrienne

---

## Example 24: Brief troubleshooting guidance (email)

Hi Dherushni,
As mentioned in my email about JM Valley, this is most likely because the updates were not pushed through to production. To ensure everything looks correct, just rerun the pipeline, which should ensure everything is correctly populated.
Thanks,
Adrienne

---

## Example 25: One-line pipeline change confirmation (email)

Hi Dheru,
The pipeline has been changed from 09:40 UTC (11:40 SAST) to 08:40 UTC (10:40 SAST).
Thanks,
Adrienne

---

## Example 26: Short confirmation with follow-up question (email)

Hi John,
Yes, I think that will be fine.
As for the walkthrough, would you like us to walk through the entire Vantage Point platform, or do you have key areas you'd like us to focus on?
Thanks,
Adrienne

---

## Example 27: Multi-topic update with open action items (email)

Hi John,
1. Snapshot Builder
I've scoped out a bunch of work for the snapshot builder. I've split the work between UI and Python work, as it's likely that different people will be working on the backend and frontend features at the same time. I believe you've already approved most of these stories.
Mieke is currently getting set up with Vantage Point locally, so she will be able to start helping with the UI changes soon.
Toby is currently handling the Python side of things, as he is familiar with the framework.
2. Agent Framework
I haven't managed to look into use cases for the agent framework today but will do so before our chat tomorrow afternoon.
In addition, it might be worthwhile to start chatting through the next tools that you want the agents to be able to have access to in order to provide the most useful agent integrations.
Thanks,
Adrienne

---

## Example 28: Multi-topic update with structured handover and technical proposal

Hi John,
Wednesday Meeting
I can make any time on Wednesday before 17:30, except between 12:30 and 13:30 SAST.
Handover Plan
Snapshot Builder: I plan to scope out a number of updates before I leave. I'll work with Toby to ensure he has enough on the Python side, and Mieke can continue with the UI updates, so there's still momentum while I'm away.
Mobile App: My goal is to have a first usable version working before I go on leave. I'll start the process of setting up with the Google Play and Apple App Stores, but if those haven't completed before I leave, I'll hand over to Anthony and Justin so those processes can continue in my absence.
Agent Framework
Pipeline and script failures are already recorded in VantagePoint with all the relevant metadata and context. My suggestion is to have agents query VantagePoint directly rather than routing through DevOps for the actual analysis.
The existing tool sets are focused around support automation and failure analysis and aren't particularly skewed towards QSR. The next step would be to identify which tool sets give agents the most leverage across the system. My current thinking on what needs to be built out:
User Script Investigation Tool
* Read output logs for a given user script (failures and last successful run)
* Check whether script metadata changed between runs, e.g. file size, snapshot configuration for the relevant user script type
* Identify whether there was a change on the git branch and when
* Surface a usable summary of what changed and what likely went wrong
ETL Investigation Tool
* Same pattern as above: query ETL logs, find the last successful run, compare against current output
* Understand how the ETL is structured and what data it ingests, so the summary is meaningful
DBT Job Investigation Tool
* Query the DBT job run and identify which models were affected
* Determine what changed and surface the likely cause of the failure
The idea is to configure agents with the appropriate tool sets per investigation type, rather than building one agent that tries to do everything. I will scope these out as a starting point.
Thanks,
Adrienne
