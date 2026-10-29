# Oral incident coordinator
The user described this synthetic project in a short interview and supplied this Markdown instead of a source directory.
## Modules
### Intake
An operator enters an incident summary and chooses a severity. There is no automatic severity classifier.
### Assignment
The coordinator assigns one on-call owner and records that owner's acknowledgement.
## Threads
### Escalation Flow
If the owner has not acknowledged within ten minutes, the coordinator alerts the backup owner. The alert is recorded once; a later acknowledgement does not erase it.
