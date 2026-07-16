---
prompt_id: rewrite.revision
stage: bounded_revision
---

Apply one bounded revision pass to the named audit/remediation items. Change only the approved
sections or semantic objects, preserve all unaffected evidence and IDs, and return a traceable
description of each change. If a requested change would require an unsupported fact or new human
decision, leave it unresolved and route it instead of guessing.
