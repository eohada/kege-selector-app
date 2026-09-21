\# LOW CONTEXT MODE — MANDATORY



Your highest priority for this repository is minimizing file reads,

repository exploration, searches, commands, and context consumption.



This rule overrides any default tendency to deeply explore the codebase.



\## ABSOLUTE DEFAULT



DO NOT explore the repository before making a localized change.



For ordinary tasks, use this workflow:



USER REQUEST

→ identify likely target file(s)

→ search exact symbol inside those files

→ read smallest relevant ranges

→ edit

→ verify edited ranges

→ STOP



Never perform general codebase research unless the task explicitly requires it.



\---



\## HARD EXPLORATION LIMIT



For a normal localized task:



\- Maximum unique source files read before editing: 5

\- Maximum repository-wide searches before editing: 2

\- Maximum investigative shell commands before editing: 3



If you reach one of these limits:



STOP EXPLORING.



Use the information already collected and make the edit.



Do not exceed the limit simply because additional context may be useful.



\---



\## LARGE FILE RULE



Never reconstruct a large file by reading many separate chunks.



Forbidden behavior:



read lines 10-30

read lines 30-60

read lines 120-140

read lines 180-250

read lines 350-375

read lines 434-442

read lines 520-535

read lines 590-608

read lines 620-645

read lines 640-666

read lines 670-688



This is considered wasteful full-file reconstruction.



Instead:



1\. Search for the exact selector / id / class / function / visible text.

2\. Read one relevant range around the match.

3\. Read at most one additional nearby range if necessary.

4\. Edit.



Do not inspect unrelated portions of the same file.



\---



\## REPEAT READ PROHIBITION



Do not read the same source file repeatedly in many non-contiguous ranges.



For localized work, a source file should normally be read no more than

2–3 times before editing.



If more reads seem necessary, perform an exact text/symbol search instead.



\---



\## USER-SPECIFIED SCOPE IS AUTHORITATIVE



When the user names a file or files, those files define the initial scope.



Example:



If the user asks to modify:



task\_workspace.html

task\_workspace.css



then ONLY inspect those files initially.



Do not inspect:

\- other pages

\- unrelated templates

\- backend code

\- unrelated JS

\- unrelated CSS

\- changelogs

\- documentation

\- route definitions



unless the requested change cannot be completed without them.



\---



\## AGENTS.MD



AGENTS.md contains persistent architectural context.



Use existing information from AGENTS.md instead of rediscovering the project.



Do not read AGENTS.md repeatedly during the same task.



Do not perform repository exploration merely to verify information already

documented there unless there is evidence that it is outdated.



\---



\## NO REPOSITORY RECONNAISSANCE



Do NOT do any of the following by default:



\- "Explore the codebase"

\- "Understand the architecture"

\- "Inspect related components"

\- "Find how similar pages work"

\- "Look for patterns across the project"

\- "Review the project structure"

\- recursively enumerate source directories

\- inspect dozens of files before making a small change



These actions require a concrete reason directly related to the requested change.



\---



\## NO RESEARCH SUBAGENT



Do not spawn or delegate to a codebase research/exploration subagent for

ordinary implementation tasks.



Do not delegate repository navigation when the target files are already known.



\---



\## SEARCH, DON'T READ



When locating code, prefer exact searches such as:



\- CSS class

\- HTML id

\- visible UI text

\- function name

\- component name

\- data attribute

\- route name



After finding the match, read only enough surrounding code to safely edit it.



\---



\## EDIT EARLY



For localized tasks, begin editing as soon as the relevant implementation

has been identified.



Do not continue investigating after you already know:



\- what must change;

\- where it is;

\- and how the surrounding code works.



More context is NOT inherently better.



\---



\## VERIFICATION MUST ALSO BE TARGETED



After editing:



\- inspect the diff;

\- inspect changed lines;

\- run the smallest relevant check if needed.



Do NOT rescan the repository after editing.



Do NOT reopen dozens of surrounding sections to "ensure consistency".



\---



\## CHANGELOG RULE



Do not read or update CHANGELOG.md unless the user explicitly requests it.



Do not update documentation as a side effect of a localized implementation

task unless required for correctness.



\---



\## TOKEN ECONOMY



Optimize for:



CORRECT CHANGE / MINIMUM CONTEXT



not:



MAXIMUM UNDERSTANDING / MAXIMUM CONTEXT



Reading fewer files is considered better behavior when correctness is preserved.



\---



\## STOP CONDITION



Once enough information exists to safely perform the requested change:



STOP USING SEARCH/READ TOOLS.



EDIT THE CODE.



This stop condition is mandatory.

